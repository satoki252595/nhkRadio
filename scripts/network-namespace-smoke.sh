#!/usr/bin/env bash
set -Eeuo pipefail

runtime_image="${1:?usage: network-namespace-smoke.sh IMAGE [CONTAINER_NAME]}"
container_name="${2:-nhk-network-smoke-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-0}}"
peer_name="${container_name}-peer"

if [[ ! "$container_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
  echo "invalid smoke container name: $container_name" >&2
  exit 2
fi

smoke_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/nhk-radio-smoke.XXXXXX")"
output_dir="$smoke_dir/output"
vpn_config="$smoke_dir/vpn.ovpn"

cleanup() {
  docker rm --force "$peer_name" >/dev/null 2>&1 || true
  docker rm --force "$container_name" >/dev/null 2>&1 || true
  rm --force "$output_dir/series.json" "$vpn_config"
  rmdir "$output_dir" "$smoke_dir" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

docker rm --force "$container_name" >/dev/null 2>&1 || true
docker rm --force "$peer_name" >/dev/null 2>&1 || true
docker image inspect "$runtime_image" >/dev/null

install -d -m 0700 "$output_dir"
install -m 0600 /dev/null "$vpn_config"
printf 'client\n' > "$vpn_config"
chgrp "$(id -g)" "$vpn_config"
chmod 0640 "$vpn_config"

# Exercise the data exporter's production read-only boundary without network calls.
docker run \
  --name "$container_name" --rm --network none \
  --user "$(id -u):$(id -g)" \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
  --tmpfs /run:rw,nosuid,nodev,noexec,size=16m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --mount "type=bind,source=${output_dir},target=/output" \
  --env NHK_API_KEY=smoke-key \
  "$runtime_image" \
  python -m nhk_recorder.data_export --days 0 --past-days 0 --output-dir /output
test -s "$output_dir/series.json"

if [[ ! -c /dev/net/tun ]]; then
  sudo install -d -m 0755 /dev/net
  sudo modprobe tun
  if [[ -e /dev/net/tun ]]; then
    echo "/dev/net/tun exists but is not a character device" >&2
    exit 1
  fi
  sudo mknod /dev/net/tun c 10 200
fi
if [[ ! -c /dev/net/tun ]]; then
  echo "/dev/net/tun is unavailable" >&2
  exit 1
fi
sudo chmod 0600 /dev/net/tun

host_route_before="$(ip -json route show default | sha256sum | awk '{print $1}')"
test -n "$host_route_before"

# The initial sidecar process must read the config with the production security flags.
docker run --detach \
  --name "$container_name" \
  --init \
  --read-only \
  --dns 8.8.8.8 \
  --dns 1.1.1.1 \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
  --tmpfs /run:rw,nosuid,nodev,noexec,size=16m \
  --cap-drop ALL \
  --cap-add NET_ADMIN \
  --group-add "$(id -g)" \
  --device /dev/net/tun \
  --security-opt no-new-privileges \
  --mount "type=bind,source=${vpn_config},target=/vpn/vpn.ovpn,readonly" \
  "$runtime_image" \
  python -c 'from pathlib import Path; import time; Path("/vpn/vpn.ovpn").read_bytes(); time.sleep(120)' \
  >/dev/null

# A capability-free peer inherits the sidecar DNS and can use the shared namespace.
timeout --signal=TERM --kill-after=5s 30s docker run \
  --name "$peer_name" \
  --rm \
  --network "container:${container_name}" \
  --user "$(id -u):$(id -g)" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --entrypoint /bin/python \
  "$runtime_image" \
  -c 'from pathlib import Path; import socket; resolv = Path("/etc/resolv.conf").read_text(); assert "nameserver 8.8.8.8" in resolv, resolv; [socket.create_connection((host, 443), timeout=10).close() for host in ("program-api.nhk.jp", "radiko.jp")]'

# Prove that NET_ADMIN and /dev/net/tun are scoped to this namespace.
docker exec "$container_name" ip tuntap add dev nhk-smoke-tun mode tun
docker exec "$container_name" ip link set nhk-smoke-tun up
docker exec "$container_name" ip route del default
docker exec "$container_name" ip route add blackhole default

if docker exec "$container_name" python -c \
  'import socket; socket.create_connection(("github.com", 443), timeout=5).close()' \
  >/dev/null 2>&1; then
  echo "container remained externally reachable after its default route was blocked" >&2
  exit 1
fi

# Breaking the container route must not break the GitHub-hosted runner route.
curl --fail --silent --show-error --max-time 10 https://github.com/robots.txt >/dev/null
host_route_during="$(ip -json route show default | sha256sum | awk '{print $1}')"
if [[ "$host_route_during" != "$host_route_before" ]]; then
  echo "host default route changed while the isolated container was running" >&2
  exit 1
fi

cleanup
host_route_after="$(ip -json route show default | sha256sum | awk '{print $1}')"
if [[ "$host_route_after" != "$host_route_before" ]]; then
  echo "host default route changed after isolated container cleanup" >&2
  exit 1
fi

echo "network namespace smoke passed: container route changes did not affect the host"
