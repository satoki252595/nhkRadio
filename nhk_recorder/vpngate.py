"""VPN Gate クライアント (筑波大学の無料VPNサービス)。

CSV API からJapan serverリストを取得し、安全性を検証したOpenVPN設定
ファイル(.ovpn)を生成する。

詳細: docs/radiko-vpn-setup.md
"""

import base64
import csv
import logging
import os
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

VPNGATE_CSV_URL = "https://www.vpngate.net/api/iphone/"

_ALLOWED_OVPN_DIRECTIVES = frozenset({
    "auth",
    "cipher",
    "client",
    "data-ciphers",
    "dev",
    "nobind",
    "persist-key",
    "persist-tun",
    "proto",
    "remote",
    "resolv-retry",
    "verb",
})
_ALLOWED_INLINE_BLOCKS = frozenset({"ca", "cert", "key", "tls-auth", "tls-crypt"})


def _validate_ovpn_config(config: str) -> None:
    """VPN Gate の標準的な接続設定以外を root の OpenVPN へ渡さない。"""
    inline_block: str | None = None
    for line_number, raw_line in enumerate(config.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if inline_block is not None:
            if line.casefold() == f"</{inline_block}>":
                inline_block = None
            continue
        if line.startswith("<") and line.endswith(">"):
            block = line[1:-1].strip().casefold()
            if block.startswith("/") or block not in _ALLOWED_INLINE_BLOCKS:
                raise ValueError(
                    "許可されていない OpenVPN inline block "
                    f"({line_number}行目): {line}"
                )
            inline_block = block
            continue
        directive = line.split(maxsplit=1)[0].casefold()
        if directive not in _ALLOWED_OVPN_DIRECTIVES:
            raise ValueError(
                f"許可されていない OpenVPN directive ({line_number}行目): {directive}"
            )
    if inline_block is not None:
        raise ValueError(f"OpenVPN inline block が閉じていません: <{inline_block}>")


@dataclass
class VpnGateServer:
    hostname: str
    ip: str
    score: int
    ping: int
    speed: int
    country_short: str
    num_sessions: int
    ovpn_config_b64: str

    def write_ovpn(self, path: Path) -> None:
        """OpenVPN設定ファイルを書き出す。

        OpenVPN 2.6+ は AES-128-CBC をデフォルトの data-ciphers に含めないが、
        VPN Gate サーバーの多くがこの cipher を使うため、明示的に追加する。
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        config = base64.b64decode(self.ovpn_config_b64).decode("utf-8", errors="replace")
        _validate_ovpn_config(config)

        # OpenVPN 2.6+ 互換: VPN Gate が使う AES-128-CBC を data-ciphers に追加
        if "data-ciphers" not in config:
            config += "\ndata-ciphers AES-256-GCM:AES-128-GCM:CHACHA20-POLY1305:AES-128-CBC\n"

        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                fd = -1
                f.write(config)
        finally:
            if fd >= 0:
                os.close(fd)


def fetch_jp_servers(limit: int = 5) -> list[VpnGateServer]:
    """VPN Gate から日本のサーバーを取得し、スコア順に返す。

    Args:
        limit: 上位N件を返す

    Returns:
        VpnGateServerのリスト (スコア降順)

    Note:
        VPN Gate CSV自体には「日本のどのエリア(関東/関西)か」の情報はない。
        エリアを特定するにはVPN接続後にRadiko auth2のレスポンスで判定する。
    """
    try:
        resp = httpx.get(VPNGATE_CSV_URL, timeout=30)
        resp.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.error("VPN Gate CSV取得失敗: %s", e)
        return []

    # CSV仕様: 1行目=コメント, 2行目=ヘッダ(*で開始), 最終行=*の区切り
    text = resp.text
    lines = text.splitlines()
    # "*" で始まる行と空行をスキップして、最初の "#HostName" をヘッダーとする
    # 実際のフォーマット: 1行目 "*vpn_servers" / 2行目 "#HostName,IP,Score,..."
    data_lines = []
    for line in lines:
        if line.startswith("*") or not line.strip():
            continue
        data_lines.append(line)

    if len(data_lines) < 2:
        logger.error("VPN Gate CSVの形式異常")
        return []

    # 1行目はヘッダ (#HostName,...)
    reader = csv.reader(StringIO("\n".join(data_lines)))
    rows = list(reader)
    header = rows[0]
    data_rows = rows[1:]

    # 列インデックスを取得 (先頭の#を除去)
    clean_header = [h.lstrip("#") for h in header]
    try:
        idx = {
            "HostName": clean_header.index("HostName"),
            "IP": clean_header.index("IP"),
            "Score": clean_header.index("Score"),
            "Ping": clean_header.index("Ping"),
            "Speed": clean_header.index("Speed"),
            "CountryShort": clean_header.index("CountryShort"),
            "NumVpnSessions": clean_header.index("NumVpnSessions"),
            "OpenVPN_ConfigData_Base64": clean_header.index("OpenVPN_ConfigData_Base64"),
        }
    except ValueError as e:
        logger.error("VPN Gate CSVヘッダ欠損: %s", e)
        return []

    servers: list[VpnGateServer] = []
    for row in data_rows:
        if len(row) < max(idx.values()) + 1:
            continue
        if row[idx["CountryShort"]] != "JP":
            continue
        try:
            servers.append(
                VpnGateServer(
                    hostname=row[idx["HostName"]],
                    ip=row[idx["IP"]],
                    score=int(row[idx["Score"]]),
                    ping=int(row[idx["Ping"]] or 0),
                    speed=int(row[idx["Speed"]] or 0),
                    country_short=row[idx["CountryShort"]],
                    num_sessions=int(row[idx["NumVpnSessions"]] or 0),
                    ovpn_config_b64=row[idx["OpenVPN_ConfigData_Base64"]],
                )
            )
        except (ValueError, IndexError):
            continue

    # スコア降順でソート
    servers.sort(key=lambda s: s.score, reverse=True)
    logger.info("VPN Gate: 日本サーバー %d台を取得 (上位%d返却)", len(servers), min(limit, len(servers)))
    return servers[:limit]


def geolocate_region(ip: str) -> str:
    """IPアドレスから日本国内のリージョン(関東/関西/その他)を推定する。

    ip-api.com (無料、認証不要、45req/分) を使用。
    Returns: "kanto" (関東), "kansai" (関西), "other" (その他), "" (判定失敗)
    """
    try:
        resp = httpx.get(
            f"http://ip-api.com/json/{ip}?fields=status,country,regionName,region",
            timeout=10,
        )
        if resp.status_code != 200:
            return ""
        data = resp.json()
        if data.get("status") != "success" or data.get("country") != "Japan":
            return ""
        region_name = data.get("regionName", "")
        # 都道府県 → リージョン判定
        kanto = {"Tokyo", "Kanagawa", "Saitama", "Chiba", "Ibaraki", "Tochigi", "Gunma"}
        kansai = {"Osaka", "Kyoto", "Hyogo", "Nara", "Shiga", "Wakayama"}
        if region_name in kanto:
            return "kanto"
        if region_name in kansai:
            return "kansai"
        return "other"
    except (httpx.RequestError, ValueError):
        return ""


def candidate_fetch_limit(rank: int, count: int) -> int:
    """How many top-scoring servers to fetch for a ranked write.

    A single server keeps the historical ``rank + 1`` window. Multiple
    candidates are always the top ``count`` servers; ``rank`` only rotates
    which of those is written first.
    """
    if count == 1:
        return rank + 1
    return count


def select_candidates(
    servers: list[VpnGateServer],
    rank: int,
    count: int,
) -> list[VpnGateServer]:
    """Pick up to ``count`` servers, starting at ``rank``.

    ``count == 1`` is the historical data-update behavior: exactly
    ``servers[rank]``, or an empty list when that index does not exist.
    Larger counts walk forward and wrap, and never repeat a server.
    """
    if count < 1 or rank < 0 or not servers:
        return []
    if count == 1:
        if rank >= len(servers):
            return []
        return [servers[rank]]

    start = rank % len(servers)
    chosen: list[VpnGateServer] = []
    for offset in range(count):
        chosen.append(servers[(start + offset) % len(servers)])
        if len(chosen) == len(servers):
            break
    return chosen


def find_server_for_region(region: str, limit: int = 5) -> VpnGateServer | None:
    """指定リージョン(kanto/kansai)のVPNサーバーを探す。

    IPジオロケーションで絞り込み、該当するものがなければ None。
    """
    servers = fetch_jp_servers(limit=50)  # 上位50台から探索
    for srv in servers:
        loc = geolocate_region(srv.ip)
        logger.info("  検証: %s (%s) -> %s", srv.hostname, srv.ip, loc or "unknown")
        if loc == region:
            return srv
    return None


def _print_server(chosen: VpnGateServer, *, index: int | None = None) -> None:
    prefix = f"  [{index}] " if index is not None else "  "
    print(f"{prefix}HostName: {chosen.hostname}")
    print(f"  IP: {chosen.ip}")
    print(f"  Score: {chosen.score:,}")
    print(f"  Ping: {chosen.ping}ms / Speed: {chosen.speed:,}bps")
    print(f"  Sessions: {chosen.num_sessions}")


def _write_manifest(directory: Path, rows: list[tuple[str, VpnGateServer]]) -> None:
    lines = [
        f"{filename}\t{server.hostname}\t{server.ip}\t{server.score}\n"
        for filename, server in rows
    ]
    path = directory / "manifest.tsv"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.writelines(lines)
    finally:
        if fd >= 0:
            os.close(fd)


def main():
    """CLI: JP VPN サーバーの .ovpn を書き出す。

    使い方:
        python -m nhk_recorder.vpngate vpn.ovpn              # 最良の日本サーバー
        python -m nhk_recorder.vpngate vpn.ovpn --region kanto  # 関東(東京等)
        python -m nhk_recorder.vpngate vpn.ovpn --region kansai # 関西(大阪等)
        python -m nhk_recorder.vpngate /vpn/candidates --count 4 --rank 1
            # rank から最大4台。output はディレクトリ
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="VPN Gate から日本のVPN .ovpn 取得")
    parser.add_argument(
        "output", nargs="?", default="vpn.ovpn",
        help="出力先 (.ovpn ファイル、または --count>1 のときディレクトリ)",
    )
    parser.add_argument("--rank", type=int, default=0, help="何番目から使うか (0=最良)")
    parser.add_argument(
        "--count", type=int, default=1,
        help="書き出す候補数 (1-4, 既定 1)。2以上なら output はディレクトリ",
    )
    parser.add_argument(
        "--region", choices=["kanto", "kansai", "any"], default="any",
        help="対象リージョン (kanto=関東/kansai=関西)",
    )
    args = parser.parse_args()
    if args.rank < 0 or not 1 <= args.count <= 4:
        parser.error("--rank は 0 以上、--count は 1 から 4 を指定してください")
    if args.region in ("kanto", "kansai") and args.count != 1:
        parser.error("--region 指定時は --count 1 のみ対応です")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.region in ("kanto", "kansai"):
        chosen = find_server_for_region(args.region)
        if not chosen:
            print(f"{args.region} エリアのVPNサーバーが見つかりません", file=sys.stderr)
            sys.exit(1)
        chosen_list = [chosen]
    else:
        servers = fetch_jp_servers(limit=candidate_fetch_limit(args.rank, args.count))
        chosen_list = select_candidates(servers, args.rank, args.count)
        if not chosen_list:
            print("適切なVPN Gateサーバーが見つかりません", file=sys.stderr)
            sys.exit(1)

    if args.count == 1:
        chosen = chosen_list[0]
        out = Path(args.output)
        chosen.write_ovpn(out)
        print(f"✓ OVPN書き出し: {out}")
        _print_server(chosen)
        if args.region in ("kanto", "kansai"):
            print(f"  Region: {args.region}")
        return

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, VpnGateServer]] = []
    for index, chosen in enumerate(chosen_list, start=1):
        filename = f"candidate-{index:02d}.ovpn"
        chosen.write_ovpn(out_dir / filename)
        written.append((filename, chosen))
    _write_manifest(out_dir, written)
    print(f"✓ OVPN候補 {len(written)}件: {out_dir}")
    for index, (filename, chosen) in enumerate(written, start=1):
        _print_server(chosen, index=index)
        print(f"  File: {filename}")


if __name__ == "__main__":
    main()
