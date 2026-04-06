"""VPN Gate クライアント (筑波大学の無料VPNサービス)。

CSV API からJapan serverリストを取得し、OpenVPN設定ファイル(.ovpn)を生成する。
GitHub Actions では別途 openvpn-connect-action 等で接続する。

詳細: docs/radiko-vpn-setup.md
"""

import base64
import csv
import logging
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

VPNGATE_CSV_URL = "https://www.vpngate.net/api/iphone/"


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

        # OpenVPN 2.6+ 互換: VPN Gate が使う AES-128-CBC を data-ciphers に追加
        if "data-ciphers" not in config:
            config += "\ndata-ciphers AES-256-GCM:AES-128-GCM:CHACHA20-POLY1305:AES-128-CBC\n"

        with open(path, "w", encoding="utf-8") as f:
            f.write(config)


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


def main():
    """CLI: JP VPN サーバーの .ovpn を書き出す。

    使い方:
        python -m nhk_recorder.vpngate vpn.ovpn              # 最良の日本サーバー
        python -m nhk_recorder.vpngate vpn.ovpn --region kanto  # 関東(東京等)
        python -m nhk_recorder.vpngate vpn.ovpn --region kansai # 関西(大阪等)
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="VPN Gate から日本のVPN .ovpn 取得")
    parser.add_argument("output", nargs="?", default="vpn.ovpn", help="出力先パス")
    parser.add_argument("--rank", type=int, default=0, help="何番目を使うか (0=最良)")
    parser.add_argument(
        "--region", choices=["kanto", "kansai", "any"], default="any",
        help="対象リージョン (kanto=関東/kansai=関西)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.region in ("kanto", "kansai"):
        chosen = find_server_for_region(args.region)
        if not chosen:
            print(f"{args.region} エリアのVPNサーバーが見つかりません", file=sys.stderr)
            sys.exit(1)
    else:
        servers = fetch_jp_servers(limit=args.rank + 1)
        if not servers or args.rank >= len(servers):
            print("適切なVPN Gateサーバーが見つかりません", file=sys.stderr)
            sys.exit(1)
        chosen = servers[args.rank]

    out = Path(args.output)
    chosen.write_ovpn(out)
    print(f"✓ OVPN書き出し: {out}")
    print(f"  HostName: {chosen.hostname}")
    print(f"  IP: {chosen.ip}")
    print(f"  Score: {chosen.score:,}")
    print(f"  Ping: {chosen.ping}ms / Speed: {chosen.speed:,}bps")
    print(f"  Sessions: {chosen.num_sessions}")
    if args.region in ("kanto", "kansai"):
        print(f"  Region: {args.region}")


if __name__ == "__main__":
    main()
