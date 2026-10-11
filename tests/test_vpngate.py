import base64
import stat
import sys
from unittest.mock import patch

import pytest

from nhk_recorder.vpngate import (
    VpnGateServer,
    candidate_fetch_limit,
    main,
    select_candidates,
)


def _server(config: bytes) -> VpnGateServer:
    return VpnGateServer(
        hostname="vpn.example",
        ip="192.0.2.1",
        score=1,
        ping=1,
        speed=1,
        country_short="JP",
        num_sessions=1,
        ovpn_config_b64=base64.b64encode(config).decode(),
    )


def test_write_ovpn_uses_private_permissions(tmp_path):
    server = _server(b"client\n<ca>\ncertificate\n</ca>\n")
    path = tmp_path / "vpn.ovpn"

    server.write_ovpn(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text().startswith("client\n")


@pytest.mark.parametrize(
    "directive",
    ["daemon", "management 0.0.0.0 7505", "plugin evil.so"],
)
def test_write_ovpn_rejects_unsafe_directives(tmp_path, directive):
    path = tmp_path / "vpn.ovpn"

    with pytest.raises(ValueError, match="許可されていない"):
        _server(f"client\n{directive}\n".encode()).write_ovpn(path)

    assert not path.exists()


@pytest.mark.parametrize("rank", range(5))
def test_main_writes_requested_server_rank(tmp_path, rank):
    servers = [_server(f"client\n# server {i}\n".encode()) for i in range(5)]
    output = tmp_path / "vpn.ovpn"

    with (
        patch.object(sys, "argv", ["vpngate", str(output), "--rank", str(rank)]),
        patch(
            "nhk_recorder.vpngate.fetch_jp_servers",
            return_value=servers[: rank + 1],
        ) as fetch,
    ):
        main()

    fetch.assert_called_once_with(limit=rank + 1)
    assert f"# server {rank}" in output.read_text()


def test_candidate_fetch_limit_preserves_single_rank_and_covers_rotation():
    assert candidate_fetch_limit(0, 1) == 1
    assert candidate_fetch_limit(4, 1) == 5
    assert candidate_fetch_limit(0, 4) == 4
    assert candidate_fetch_limit(4, 4) == 4


def test_select_candidates_wraps_from_starting_rank():
    servers = [_server(f"client\n# server {i}\n".encode()) for i in range(5)]
    for index, server in enumerate(servers):
        server.hostname = f"vpn-{index}"

    assert [server.hostname for server in select_candidates(servers, 4, 1)] == ["vpn-4"]
    assert [server.hostname for server in select_candidates(servers, 4, 4)] == [
        "vpn-4", "vpn-0", "vpn-1", "vpn-2",
    ]
    # data-update fetches only the top 4, so rank 4 wraps to the best server.
    assert [server.hostname for server in select_candidates(servers[:4], 4, 4)] == [
        "vpn-0", "vpn-1", "vpn-2", "vpn-3",
    ]
    assert [server.hostname for server in select_candidates(servers[:2], 0, 4)] == [
        "vpn-0", "vpn-1",
    ]
    assert select_candidates(servers, 5, 1) == []


def test_main_writes_rotated_candidate_directory(tmp_path):
    servers = [_server(f"client\n# server {i}\n".encode()) for i in range(8)]
    for index, server in enumerate(servers):
        server.hostname = f"vpn-{index}"
        server.ip = f"192.0.2.{index + 1}"
        server.score = 1000 - index
    output = tmp_path / "candidates"

    def fake_fetch(limit=5):
        return servers[:limit]

    with (
        patch.object(sys, "argv", ["vpngate", str(output), "--count", "4", "--rank", "2"]),
        patch("nhk_recorder.vpngate.fetch_jp_servers", side_effect=fake_fetch) as fetch,
    ):
        main()

    fetch.assert_called_once_with(limit=4)
    written = [(output / f"candidate-{index:02d}.ovpn").read_text() for index in range(1, 5)]
    assert "# server 2" in written[0]
    assert "# server 3" in written[1]
    assert "# server 0" in written[2]
    assert "# server 1" in written[3]
    manifest = (output / "manifest.tsv").read_text()
    assert manifest.splitlines() == [
        "candidate-01.ovpn\tvpn-2\t192.0.2.3\t998",
        "candidate-02.ovpn\tvpn-3\t192.0.2.4\t997",
        "candidate-03.ovpn\tvpn-0\t192.0.2.1\t1000",
        "candidate-04.ovpn\tvpn-1\t192.0.2.2\t999",
    ]
    assert stat.S_IMODE((output / "manifest.tsv").stat().st_mode) == 0o600
    assert stat.S_IMODE((output / "candidate-01.ovpn").stat().st_mode) == 0o600


def test_main_rejects_count_above_four_and_region_fanout(tmp_path):
    output = tmp_path / "candidates"
    with (
        patch.object(sys, "argv", ["vpngate", str(output), "--count", "5"]),
        pytest.raises(SystemExit),
    ):
        main()
    with (
        patch.object(sys, "argv", ["vpngate", str(output), "--region", "kanto", "--count", "4"]),
        pytest.raises(SystemExit),
    ):
        main()
    assert not output.exists()
