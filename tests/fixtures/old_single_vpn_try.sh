#!/usr/bin/env bash
# Reimplementation of the pre-fix data-update sidecar (83426f8 / main 2df575e):
# start exactly one OpenVPN config and exit 1 on the first failure.
# Same hook interface as scripts/try-vpn-candidates.sh so the regression test
# can be pointed here with VPN_TRY_SCRIPT and must fail.

set -Eeuo pipefail

config_dir="$(cd "${1:?usage: old_single_vpn_try.sh CONFIG_DIR}" && pwd)"
manifest="$config_dir/manifest.tsv"
IFS=$'\t' read -r filename hostname ip _score < "$manifest"
config="$config_dir/$filename"

echo "VPN candidate 1/1: hostname=${hostname} ip=${ip} config=${filename}"

if ! start_output="$("$VPN_START_HOOK" "$config" "$hostname" "$ip" "1" 2>&1)"; then
  reason="${start_output:-openvpn failed to start}"
  echo "VPN candidate 1/1 failed: hostname=${hostname} ip=${ip} reason=${reason}"
  "$VPN_STOP_HOOK" "$config" "$hostname" "$ip" "1" || true
  echo "VPN sidecar DNS/TCP preflight failed: aborting Radiko data update" >&2
  exit 1
fi

if ! wait_output="$("$VPN_WAIT_HOOK" "$config" "$hostname" "$ip" "1" 2>&1)"; then
  echo "VPN candidate 1/1 failed: hostname=${hostname} ip=${ip} reason=${wait_output}"
  "$VPN_STOP_HOOK" "$config" "$hostname" "$ip" "1" || true
  echo "VPN sidecar DNS/TCP preflight failed: aborting Radiko data update" >&2
  exit 1
fi

if ! preflight_output="$("$VPN_PREFLIGHT_HOOK" "$config" "$hostname" "$ip" "1" 2>&1)"; then
  reason="${preflight_output:-VPN sidecar DNS/TCP preflight failed}"
  echo "VPN candidate 1/1 failed: hostname=${hostname} ip=${ip} reason=${reason}"
  "$VPN_STOP_HOOK" "$config" "$hostname" "$ip" "1" || true
  echo "VPN sidecar DNS/TCP preflight failed: aborting Radiko data update" >&2
  exit 1
fi

echo "VPN sidecar DNS/TCP preflight passed: Radiko export enabled"
echo "VPN candidate 1/1 selected: hostname=${hostname} ip=${ip}"
exit 0
