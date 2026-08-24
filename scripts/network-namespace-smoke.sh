#!/usr/bin/env bash
set -Eeuo pipefail

runtime_image="${1:?usage: network-namespace-smoke.sh IMAGE [CONTAINER_NAME]}"
container_name="${2:-nhk-network-smoke-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-0}}"

if [[ ! "$container_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
  echo "invalid smoke container name: $container_name" >&2
  exit 2
fi

cleanup() {
  docker rm --force "$container_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

cleanup
docker image inspect "$runtime_image" >/dev/null

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

docker run --detach \
  --name "$container_name" \
  --init \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
  --tmpfs /run:rw,nosuid,nodev,noexec,size=16m \
  --cap-drop ALL \
  --cap-add NET_ADMIN \
  --device /dev/net/tun \
  --security-opt no-new-privileges \
  "$runtime_image" \
  sleep 120 >/dev/null

# The container can reach GitHub before its own route is changed.
docker exec "$container_name" python -c \
  'import socket; socket.create_connection(("github.com", 443), timeout=10).close()'

# Prove that NET_ADMIN and /dev/net/tun are scoped to this namespace.
docker exec "$container_name" ip tuntap add dev nhk-smoke-tun mode tun
docker exec "$container_name" ip link set nhk-smoke-tun up
docker exec "$container_name" ip route del default
docker exec "$container_name" ip route add blackhole default
docker exec "$container_name" ip route show default | grep -Fqx 'blackhole default'

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
