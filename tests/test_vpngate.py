import base64
import stat
import sys
from unittest.mock import patch

import pytest

from nhk_recorder.vpngate import (
    VpnGateServer,
    candidate_fetch_limit,
    diversify_servers,
    geolocate_prefectures,
    main,
    prefecture_for_area,
    prioritize_servers_for_areas,
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
    # Multiple candidates fetch a wider pool so subnet diversification
    # has somewhere to diversify to; rank only rotates the order.
    assert candidate_fetch_limit(0, 4) == 16
    assert candidate_fetch_limit(4, 4) == 16


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

    fetch.assert_called_once_with(limit=16)
    written = [(output / f"candidate-{index:02d}.ovpn").read_text() for index in range(1, 5)]
    assert "# server 2" in written[0]
    assert "# server 3" in written[1]
    assert "# server 4" in written[2]
    assert "# server 5" in written[3]
    manifest = (output / "manifest.tsv").read_text()
    assert manifest.splitlines() == [
        "candidate-01.ovpn\tvpn-2\t192.0.2.3\t998",
        "candidate-02.ovpn\tvpn-3\t192.0.2.4\t997",
        "candidate-03.ovpn\tvpn-4\t192.0.2.5\t996",
        "candidate-04.ovpn\tvpn-5\t192.0.2.6\t995",
    ]
    assert stat.S_IMODE((output / "manifest.tsv").stat().st_mode) == 0o600
    assert stat.S_IMODE((output / "candidate-01.ovpn").stat().st_mode) == 0o600


def _server_at(hostname: str, ip: str, score: int = 1) -> VpnGateServer:
    server = _server(b"client\n")
    server.hostname = hostname
    server.ip = ip
    server.score = score
    return server


def test_diversify_servers_round_robins_across_subnets():
    servers = [
        _server_at("cluster-1", "219.100.37.10", score=600),
        _server_at("cluster-2", "219.100.37.11", score=590),
        _server_at("cluster-3", "219.100.37.12", score=580),
        _server_at("cluster-4", "219.100.37.13", score=570),
        _server_at("home-osaka", "118.110.135.84", score=100),
        _server_at("home-tokyo", "203.0.113.5", score=90),
    ]

    diversified = diversify_servers(servers)

    assert [s.hostname for s in diversified] == [
        "cluster-1", "home-osaka", "home-tokyo",
        "cluster-2", "cluster-3", "cluster-4",
    ]


def test_select_candidates_prefers_distinct_subnets():
    # 2026-11-07 data-update failure: the top 4 by score were all in
    # 219.100.37.0/24 and every one returned AUTH_FAILED.
    servers = [
        _server_at("cluster-1", "219.100.37.10", score=600),
        _server_at("cluster-2", "219.100.37.11", score=590),
        _server_at("cluster-3", "219.100.37.12", score=580),
        _server_at("cluster-4", "219.100.37.13", score=570),
        _server_at("home-osaka", "118.110.135.84", score=100),
        _server_at("home-tokyo", "203.0.113.5", score=90),
    ]

    chosen = select_candidates(servers, 0, 4)

    subnets = {".".join(s.ip.split(".")[:3]) for s in chosen}
    assert len(subnets) == 3
    assert chosen[0].hostname == "cluster-1"
    assert {s.hostname for s in chosen} >= {"home-osaka", "home-tokyo"}


def test_candidate_fetch_limit_widens_the_pool_for_fallback():
    assert candidate_fetch_limit(0, 4) == 16
    assert candidate_fetch_limit(0, 8) == 32
    assert candidate_fetch_limit(3, 8) == 32


def test_prefecture_for_area_maps_radiko_area_ids():
    assert prefecture_for_area("JP13") == "Tokyo"
    assert prefecture_for_area("JP27") == "Osaka"
    assert prefecture_for_area("JP1") == "Hokkaido"
    assert prefecture_for_area("JP47") == "Okinawa"
    assert prefecture_for_area("") == ""
    assert prefecture_for_area("JP99") == ""
    assert prefecture_for_area("XX13") == ""


def test_prioritize_servers_for_areas_puts_needed_prefecture_first():
    servers = [
        _server_at("tokyo-1", "203.0.113.1"),
        _server_at("osaka-1", "203.0.114.1"),
        _server_at("kyoto-1", "203.0.115.1"),
        _server_at("unknown-1", "203.0.116.1"),
    ]
    prefectures = {
        "203.0.113.1": "Tokyo",
        "203.0.114.1": "Osaka",
        "203.0.115.1": "Kyoto",
    }

    ordered = prioritize_servers_for_areas(servers, {"JP27"}, prefectures)

    # Exact prefecture first, same Kinki block next, the rest in input order.
    assert [s.hostname for s in ordered] == [
        "osaka-1", "kyoto-1", "tokyo-1", "unknown-1",
    ]
    # Without geolocation data the input order is preserved.
    assert prioritize_servers_for_areas(servers, {"JP27"}, {}) == servers
    assert prioritize_servers_for_areas(servers, set(), prefectures) == servers


def test_geolocate_prefectures_uses_one_batch_request():
    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return [
                {"status": "success", "country": "Japan",
                 "regionName": "Osaka", "query": "118.110.135.84"},
                {"status": "fail", "query": "192.0.2.1"},
                {"status": "success", "country": "United States",
                 "regionName": "California", "query": "198.51.100.7"},
            ]

    with patch(
        "nhk_recorder.vpngate.httpx.post", return_value=_Response(),
    ) as post:
        result = geolocate_prefectures(
            ["118.110.135.84", "192.0.2.1", "198.51.100.7", "118.110.135.84"],
        )

    post.assert_called_once()
    assert result == {"118.110.135.84": "Osaka"}


def test_geolocate_prefectures_returns_empty_on_network_error():
    import httpx

    with patch(
        "nhk_recorder.vpngate.httpx.post",
        side_effect=httpx.ConnectError("down"),
    ):
        assert geolocate_prefectures(["118.110.135.84"]) == {}


def test_main_rejects_count_above_eight_and_region_fanout(tmp_path):
    output = tmp_path / "candidates"
    with (
        patch.object(sys, "argv", ["vpngate", str(output), "--count", "9"]),
        pytest.raises(SystemExit),
    ):
        main()
    with (
        patch.object(sys, "argv", ["vpngate", str(output), "--region", "kanto", "--count", "4"]),
        pytest.raises(SystemExit),
    ):
        main()
    assert not output.exists()
