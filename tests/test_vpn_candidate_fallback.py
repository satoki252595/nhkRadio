"""Fallback across VPN configs, with openvpn and the DNS/TCP preflight stubbed.

The production script is scripts/try-vpn-candidates.sh. Point VPN_TRY_SCRIPT at
tests/fixtures/old_single_vpn_try.sh to rerun the same assertions against the
pre-fix single-server loop; test_second_candidate_succeeds_after_auth_failed
must fail there and pass against the new script.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEW_SCRIPT = ROOT / "scripts" / "try-vpn-candidates.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def _prepare(tmp_path: Path, servers: list[tuple[str, str, str]]):
    """servers is (hostname, ip, outcome).

    outcome ``ok`` passes init and preflight. ``preflight:<reason>`` passes
    init and fails preflight. Any other outcome fails the openvpn wait.
    """
    config_dir = tmp_path / "candidates"
    config_dir.mkdir()
    manifest_lines = []
    for index, (hostname, ip, _outcome) in enumerate(servers, start=1):
        filename = f"candidate-{index:02d}.ovpn"
        (config_dir / filename).write_text(f"client\n# {hostname}\n")
        manifest_lines.append(f"{filename}\t{hostname}\t{ip}\t{1000 - index}\n")
    (config_dir / "manifest.tsv").write_text("".join(manifest_lines))

    outcomes = tmp_path / "outcomes.tsv"
    outcomes.write_text(
        "".join(f"{hostname}\t{outcome}\n" for hostname, _ip, outcome in servers)
    )
    trace = tmp_path / "trace.tsv"
    called = tmp_path / "real-binary-called"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("openvpn", "docker"):
        _write_executable(
            bin_dir / name,
            "#!/usr/bin/env bash\n"
            f"printf '%s\\n' \"{name} $*\" >> \"{called}\"\n"
            "exit 99\n",
        )

    hooks = tmp_path / "hooks"
    hooks.mkdir()
    _write_executable(
        hooks / "start",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf 'start\\t%s\\t%s\\t%s\\n' \"$4\" \"$2\" \"$3\" >> \"$VPN_TRACE\"\n",
    )
    _write_executable(
        hooks / "wait",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "hostname=\"$2\"\n"
        "outcome=\"$(awk -F '\\t' -v h=\"$hostname\" '$1 == h { print $2; exit }' \"$VPN_OUTCOMES\")\"\n"
        "if [[ \"$outcome\" == \"ok\" || \"$outcome\" == preflight:* ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "printf '%s\\n' \"$outcome\"\n"
        "exit 1\n",
    )
    _write_executable(
        hooks / "preflight",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "hostname=\"$2\"\n"
        "printf 'preflight\\t%s\\t%s\\t%s\\n' \"$4\" \"$2\" \"$3\" >> \"$VPN_TRACE\"\n"
        "outcome=\"$(awk -F '\\t' -v h=\"$hostname\" '$1 == h { print $2; exit }' \"$VPN_OUTCOMES\")\"\n"
        "if [[ \"$outcome\" == \"ok\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "printf '%s\\n' \"${outcome#preflight:}\"\n"
        "exit 1\n",
    )
    _write_executable(
        hooks / "stop",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf 'stop\\t%s\\t%s\\t%s\\n' \"$4\" \"$2\" \"$3\" >> \"$VPN_TRACE\"\n",
    )

    env = os.environ.copy()
    env.update({
        "VPN_START_HOOK": str(hooks / "start"),
        "VPN_WAIT_HOOK": str(hooks / "wait"),
        "VPN_PREFLIGHT_HOOK": str(hooks / "preflight"),
        "VPN_STOP_HOOK": str(hooks / "stop"),
        "VPN_TRACE": str(trace),
        "VPN_OUTCOMES": str(outcomes),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
    })
    for key in ("RUNTIME_IMAGE", "VPN_CONTAINER", "VPN_PROBE_CONTAINER"):
        env.pop(key, None)
    return config_dir, trace, called, env


def _run(config_dir: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    script = Path(os.environ.get("VPN_TRY_SCRIPT", str(NEW_SCRIPT)))
    if not script.is_absolute():
        script = ROOT / script
    return subprocess.run(
        ["bash", str(script), str(config_dir)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _failure_detail(result: subprocess.CompletedProcess[str], trace: Path) -> str:
    body = trace.read_text() if trace.exists() else ""
    return f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}\ntrace:\n{body}"


def test_second_candidate_succeeds_after_auth_failed(tmp_path):
    config_dir, trace, called, env = _prepare(tmp_path, [
        ("public-vpn-201", "203.0.113.10", "AUTH_FAILED"),
        ("public-vpn-088", "203.0.113.11", "ok"),
    ])

    result = _run(config_dir, env)

    assert result.returncode == 0, _failure_detail(result, trace)
    assert "VPN sidecar DNS/TCP preflight passed: Radiko export enabled" in result.stdout
    assert "hostname=public-vpn-201" in result.stdout
    assert "reason=AUTH_FAILED" in result.stdout
    assert "hostname=public-vpn-088" in result.stdout
    assert "VPN candidate 2/2 selected: hostname=public-vpn-088 ip=203.0.113.11" in result.stdout
    events = [line.split("\t") for line in trace.read_text().splitlines()]
    assert [row[0] for row in events] == ["start", "stop", "start", "preflight"]
    assert [row[2] for row in events] == [
        "public-vpn-201",
        "public-vpn-201",
        "public-vpn-088",
        "public-vpn-088",
    ]
    assert not called.exists()


def test_all_four_candidates_fail_exits_nonzero(tmp_path):
    config_dir, trace, called, env = _prepare(tmp_path, [
        ("public-vpn-201", "203.0.113.10", "AUTH_FAILED"),
        ("public-vpn-088", "203.0.113.11", "AUTH_FAILED"),
        ("public-vpn-014", "203.0.113.12", "timed out waiting for Initialization Sequence Completed"),
        ("public-vpn-003", "203.0.113.13", "preflight:VPN sidecar DNS/TCP preflight failed"),
        ("public-vpn-999", "203.0.113.14", "ok"),
    ])

    result = _run(config_dir, env)
    stdout = result.stdout
    trace_body = trace.read_text()

    assert result.returncode != 0, _failure_detail(result, trace)
    assert "VPN sidecar DNS/TCP preflight passed" not in stdout
    assert "VPN sidecar DNS/TCP preflight failed: aborting Radiko data update" in result.stderr
    assert "VPN candidates configured=5 trying=4" in stdout
    for hostname in (
        "public-vpn-201",
        "public-vpn-088",
        "public-vpn-014",
        "public-vpn-003",
    ):
        assert f"hostname={hostname}" in stdout
    assert "reason=AUTH_FAILED" in stdout
    assert "reason=timed out waiting for Initialization Sequence Completed" in stdout
    assert "reason=VPN sidecar DNS/TCP preflight failed" in stdout
    assert "public-vpn-999" not in stdout
    assert "public-vpn-999" not in trace_body
    assert len([line for line in trace_body.splitlines() if line.startswith("start\t")]) == 4
    assert len([line for line in trace_body.splitlines() if line.startswith("stop\t")]) == 4
    assert not called.exists()


def test_data_update_invokes_fallback_without_swallowing_failure():
    workflow = (ROOT / ".github/workflows/data-update.yml").read_text()
    record = (ROOT / ".github/workflows/record.yml").read_text()
    assert "cron: '30 19 * * *'" in workflow
    assert "cron: '0 21 * * *'" in record
    start = workflow.index("name: Start isolated VPN sidecar when requested")
    end = workflow.index("name: Generate data with non-privileged exporter")
    step = workflow[start:end]
    assert "bash scripts/try-vpn-candidates.sh" in step
    assert "--count 4" in step
    assert "--rank" in step
    assert "continue-on-error" not in step
    assert "exit 1" in step
    assert "Initialization Sequence Completed" not in step
