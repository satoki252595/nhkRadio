import base64
import stat
import sys
from unittest.mock import patch

import pytest

from nhk_recorder.vpngate import VpnGateServer, main


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
