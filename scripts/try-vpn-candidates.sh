#!/usr/bin/env bash
# Try up to 4 VPN Gate OpenVPN configs in order.
#
# Each candidate: start openvpn, wait for "Initialization Sequence Completed",
# then DNS/TCP preflight. On failure the openvpn process is stopped and the
# next config is tried. Exit 0 on the first success. Exit 1 when every
# candidate fails — callers must not treat that as a successful run.
#
# Production uses docker. Tests stub the three steps with:
#   VPN_START_HOOK, VPN_WAIT_HOOK, VPN_PREFLIGHT_HOOK, VPN_STOP_HOOK
# Each hook is called as: hook CONFIG HOSTNAME IP INDEX

set -Eeuo pipefail

config_dir="${1:?usage: try-vpn-candidates.sh CONFIG_DIR}"
max_candidates=4

if [[ ! -d "$config_dir" ]]; then
  echo "VPN candidate directory not found: $config_dir" >&2
  exit 1
fi
config_dir="$(cd "$config_dir" && pwd)"
manifest="$config_dir/manifest.tsv"
if [[ ! -s "$manifest" ]]; then
  echo "VPN candidate manifest missing: $manifest" >&2
  exit 1
fi

require_docker_env() {
  : "${RUNTIME_IMAGE:?RUNTIME_IMAGE is required}"
  : "${VPN_CONTAINER:?VPN_CONTAINER is required}"
  : "${VPN_PROBE_CONTAINER:?VPN_PROBE_CONTAINER is required}"
}

single_line() {
  local text="$1"
  text="${text//$'\r'/}"
  # Drop trailing whitespace (hooks print a trailing newline) before collapsing.
  text="${text%"${text##*[![:space:]]}"}"
  text="${text//$'\n'/; }"
  printf '%s\n' "$text"
}

stop_candidate() {
  if [[ -n "${VPN_STOP_HOOK:-}" ]]; then
    "$VPN_STOP_HOOK" "$@" || true
    return
  fi
  require_docker_env
  docker rm --force "$VPN_PROBE_CONTAINER" >/dev/null 2>&1 || true
  docker rm --force "$VPN_CONTAINER" >/dev/null 2>&1 || true
}

start_candidate() {
  local config="$1"
  if [[ -n "${VPN_START_HOOK:-}" ]]; then
    "$VPN_START_HOOK" "$@"
    return
  fi
  require_docker_env
  docker rm --force "$VPN_PROBE_CONTAINER" >/dev/null 2>&1 || true
  docker rm --force "$VPN_CONTAINER" >/dev/null 2>&1 || true
  # stdout is the container id; openvpn's own log stays in `docker logs`.
  docker run --detach \
    --name "$VPN_CONTAINER" \
    --init \
    --stop-timeout 20 \
    --read-only \
    --dns 8.8.8.8 \
    --dns 1.1.1.1 \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
    --tmpfs /run:rw,nosuid,nodev,noexec,size=32m \
    --cap-drop ALL \
    --cap-add NET_ADMIN \
    --group-add "$(id -g)" \
    --device /dev/net/tun \
    --security-opt no-new-privileges \
    --mount "type=bind,source=${config},target=/vpn/vpn.ovpn,readonly" \
    "$RUNTIME_IMAGE" \
    openvpn --config /vpn/vpn.ovpn --script-security 1 --auth-nocache >/dev/null
}

wait_candidate() {
  if [[ -n "${VPN_WAIT_HOOK:-}" ]]; then
    "$VPN_WAIT_HOOK" "$@"
    return
  fi
  require_docker_env
  local attempt running
  for ((attempt = 1; attempt <= 45; attempt++)); do
    if docker logs "$VPN_CONTAINER" 2>&1 | grep -Fq 'Initialization Sequence Completed'; then
      return 0
    fi
    running="$(docker inspect --format '{{.State.Running}}' "$VPN_CONTAINER" 2>/dev/null || true)"
    if [[ "$running" != "true" ]]; then
      return 1
    fi
    sleep 1
  done
  return 1
}

preflight_candidate() {
  if [[ -n "${VPN_PREFLIGHT_HOOK:-}" ]]; then
    "$VPN_PREFLIGHT_HOOK" "$@"
    return
  fi
  require_docker_env
  timeout --signal=TERM --kill-after=5s 30s docker run \
    --name "$VPN_PROBE_CONTAINER" \
    --rm \
    --network "container:${VPN_CONTAINER}" \
    --user "$(id -u):$(id -g)" \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --entrypoint /bin/python \
    "$RUNTIME_IMAGE" \
    -c 'import socket; [socket.create_connection((host, 443), timeout=10).close() for host in ("program-api.nhk.jp", "radiko.jp")]'
}

collect_openvpn_failure_reason() {
  local logs
  logs="$(docker logs --tail 80 "$VPN_CONTAINER" 2>&1 || true)"
  if [[ -n "$logs" ]]; then
    printf '%s\n' "$logs" >&2
  fi
  if grep -Fq 'AUTH_FAILED' <<<"$logs"; then
    printf '%s\n' "AUTH_FAILED"
    return
  fi
  if grep -Fq 'Cannot resolve' <<<"$logs"; then
    printf '%s\n' "Cannot resolve"
    return
  fi
  local running code
  running="$(docker inspect --format '{{.State.Running}}' "$VPN_CONTAINER" 2>/dev/null || echo false)"
  if [[ "$running" != "true" ]]; then
    code="$(docker inspect --format '{{.State.ExitCode}}' "$VPN_CONTAINER" 2>/dev/null || echo unknown)"
    printf '%s\n' "openvpn exited (code=${code}) before Initialization Sequence Completed"
    return
  fi
  printf '%s\n' "timed out waiting for Initialization Sequence Completed"
}

declare -a files=() hosts=() ips=()
configured=0
while IFS=$'\t' read -r filename hostname ip _score || [[ -n "${filename:-}" ]]; do
  [[ -z "${filename:-}" ]] && continue
  configured=$((configured + 1))
  if (( ${#files[@]} >= max_candidates )); then
    continue
  fi
  if [[ ! "$filename" =~ ^[A-Za-z0-9._-]+$ ]] || [[ -L "$config_dir/$filename" ]] || [[ ! -f "$config_dir/$filename" ]]; then
    echo "invalid VPN candidate file: ${filename}" >&2
    exit 1
  fi
  if [[ -z "$hostname" || -z "$ip" ]]; then
    echo "invalid VPN candidate manifest row: ${filename}" >&2
    exit 1
  fi
  files+=("$filename")
  hosts+=("$hostname")
  ips+=("$ip")
done < "$manifest"

total=${#files[@]}
if (( total == 0 )); then
  echo "VPN candidate manifest has no servers" >&2
  exit 1
fi
echo "VPN candidates configured=${configured} trying=${total}"
if (( configured > total )); then
  echo "VPN candidate list truncated to ${total}"
fi

for ((i = 0; i < total; i++)); do
  index=$((i + 1))
  filename="${files[$i]}"
  hostname="${hosts[$i]}"
  ip="${ips[$i]}"
  config="$config_dir/$filename"
  echo "VPN candidate ${index}/${total}: hostname=${hostname} ip=${ip} config=${filename}"

  if ! start_output="$(start_candidate "$config" "$hostname" "$ip" "$index" 2>&1)"; then
    reason="$(single_line "${start_output:-openvpn failed to start}")"
    echo "VPN candidate ${index}/${total} failed: hostname=${hostname} ip=${ip} reason=${reason}"
    stop_candidate "$config" "$hostname" "$ip" "$index"
    continue
  fi

  if ! wait_output="$(wait_candidate "$config" "$hostname" "$ip" "$index" 2>&1)"; then
    if [[ -n "${VPN_WAIT_HOOK:-}" ]]; then
      reason="$(single_line "${wait_output:-openvpn failed}")"
    else
      reason="$(collect_openvpn_failure_reason)"
    fi
    echo "VPN candidate ${index}/${total} failed: hostname=${hostname} ip=${ip} reason=${reason}"
    stop_candidate "$config" "$hostname" "$ip" "$index"
    continue
  fi

  if ! preflight_output="$(preflight_candidate "$config" "$hostname" "$ip" "$index" 2>&1)"; then
    if [[ -n "${VPN_PREFLIGHT_HOOK:-}" ]]; then
      reason="$(single_line "${preflight_output:-VPN sidecar DNS/TCP preflight failed}")"
    else
      if [[ -n "$preflight_output" ]]; then
        printf '%s\n' "$preflight_output" >&2
      fi
      reason="VPN sidecar DNS/TCP preflight failed"
    fi
    echo "VPN candidate ${index}/${total} failed: hostname=${hostname} ip=${ip} reason=${reason}"
    stop_candidate "$config" "$hostname" "$ip" "$index"
    continue
  fi

  echo "VPN sidecar DNS/TCP preflight passed: Radiko export enabled"
  echo "VPN candidate ${index}/${total} selected: hostname=${hostname} ip=${ip}"
  exit 0
done

echo "VPN sidecar DNS/TCP preflight failed: aborting Radiko data update" >&2
exit 1
