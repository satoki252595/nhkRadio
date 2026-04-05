# Radiko対応: VPN Gate経由の実装

## 背景

GitHub ActionsのrunnerはMicrosoft Azure (米国)のIPから実行される。一方、Radiko(民放ラジオ)は**日本のIPからのみ認証を許可する**地域制限がある。

このため、GitHub Actions上でRadikoの番組表取得・録音を行うには、日本IPへのルーティングが必要となる。

## ソリューション: VPN Gate (筑波大学)

**VPN Gate** (https://www.vpngate.net/) は、筑波大学が学術実験として運営する
公開VPN中継サーバープロジェクト。日本国内のボランティアが提供する多数のVPN
サーバーに無料で接続できる。

### 利用規約の確認点

- **学術実験プロジェクト** であり、商用利用には制限がある可能性
- 個人利用・研究目的での使用は許諾されている
- Radikoの利用規約上、VPN経由のアクセスは明示禁止されていないが、**グレーゾーン**
- 録音は**個人利用の範囲**に限定すること

### Radiko利用規約について

Radikoは「放送対象地域外の聴取を目的としたVPNの使用」を禁止する旨を明記していない。
ただし、録音した音声の再配布・商用利用は利用規約で明確に禁止されている。
**本プロジェクトで録音した音声は、Notionに保存して個人で聴く用途のみ** に限定する。

## アーキテクチャ

```
┌──────────────────────────────────────────────────────┐
│ GitHub Actions Runner (Ubuntu, 米国IP)               │
│                                                      │
│  Step 1: VPN Gate CSV から日本サーバーを取得         │
│  Step 2: OpenVPN で接続 → 以降は日本IPに             │
│  Step 3: Radiko 認証 (auth1 → auth2)                 │
│  Step 4: ffmpeg で HLS 録音                          │
│  Step 5: Notion アップロード                         │
│  Step 6: VPN 切断                                    │
└──────────────────────────────────────────────────────┘
```

## 実装の構成要素

### 1. VPN Gate サーバーリスト取得

CSV API: `https://www.vpngate.net/api/iphone/`

列:
- `HostName`, `IP`, `Score`, `Ping`, `Speed`
- `CountryLong`, `CountryShort`
- `NumVpnSessions`, `Uptime`, `TotalUsers`
- `OpenVPN_ConfigData_Base64` ← ovpn設定ファイル本体(base64)

選定基準:
- `CountryShort == "JP"`
- `Score` で降順ソート → 上位サーバー
- `OpenVPN_ConfigData_Base64` を base64 デコード → `.ovpn` ファイルとして保存

### 2. OpenVPN 接続

**GitHub Action**: `kota65535/github-openvpn-connect-action@v2`

```yaml
- name: Fetch VPN Gate JP server
  id: vpn
  run: |
    curl -s https://www.vpngate.net/api/iphone/ | \
      tail -n +3 | \
      awk -F',' '$7 == "JP" {print}' | \
      sort -t',' -k3 -n -r | \
      head -1 > server.csv
    awk -F',' '{print $15}' server.csv | base64 -d > vpn.ovpn

- name: Connect to VPN
  uses: kota65535/github-openvpn-connect-action@v2
  with:
    config_file: vpn.ovpn
```

注意: VPN Gateのサーバーは**匿名認証**のため、username/passwordは不要。

### 3. Radiko 認証フロー

```python
# Step 1: auth1 → authtoken取得
GET https://radiko.jp/v2/api/auth1
  X-Radiko-App: pc_html5
  X-Radiko-App-Version: 0.0.1
  X-Radiko-User: dummy_user
  X-Radiko-Device: pc
→ レスポンスヘッダに:
  X-Radiko-AuthToken: (トークン)
  X-Radiko-KeyLength: (例 16)
  X-Radiko-KeyOffset: (例 4)

# Step 2: partialkey生成
固定キー authkey = 'bcd151073c03b352e1ef2fd66c32209da9ca0afa'
partialkey = base64(authkey[offset:offset+length])

# Step 3: auth2 → 認証確定 + エリア判定
GET https://radiko.jp/v2/api/auth2
  X-Radiko-AuthToken: (auth1で得たtoken)
  X-Radiko-Partialkey: (上記partialkey)
  X-Radiko-User: dummy_user
  X-Radiko-Device: pc
→ レスポンスbody: "JP27,大阪府,OSAKA JAPAN" (カンマ区切り)
```

エリアコード:
- `JP13`: 東京
- `JP27`: 大阪
- `JP14`: 神奈川
- etc.

### 4. 番組表取得

```
GET http://radiko.jp/v3/program/date/{YYYYMMDD}/{area_id}.xml
```

XMLレスポンス例:
```xml
<radiko>
  <stations area_id="JP27" area_name="大阪府">
    <station id="ABC">
      <name>朝日放送ラジオ</name>
      <progs>
        <prog id="..." ft="20260405140000" to="20260405150000" ...>
          <title>番組名</title>
          <pfm>出演者</pfm>
          <info>番組情報</info>
        </prog>
        ...
      </progs>
    </station>
    ...
  </stations>
</radiko>
```

### 5. ストリーム録音

```python
# タイムフリー録音 (過去7日分) または ライブ録音
ffmpeg -headers "X-Radiko-AuthToken: {authtoken}" \
  -i "https://f-radiko.smartstream.ne.jp/{station_id}/_definst_/simul-stream.stream/playlist.m3u8" \
  -t {duration_sec} \
  -c copy output.m4a
```

## リスクと対策

| リスク | 対策 |
|---|---|
| VPN Gate日本サーバーが停止・不安定 | スコア上位3台を試行、失敗時は次候補へ |
| VPN接続後のRadiko認証失敗 | area_idが `JP` プレフィックスか確認 |
| 録音中のVPN切断 | タイムアウト設定、リトライロジック |
| Radiko側でVPN IPを検出・ブロック | 検出されたら別サーバーに切り替え |
| Radiko規約変更 | 定期的に規約確認 |

## 関連リンク

- [VPN Gate](https://www.vpngate.net/)
- [kota65535/github-openvpn-connect-action](https://github.com/kota65535/github-openvpn-connect-action)
- [Radiko API解説記事(Qiita)](https://qiita.com/miyama_daily/items/4f5cd4d4ce6bbe654de3)

## 注意事項 (必読)

本機能は**個人での私的録音**の範囲で使用すること。
- 録音した音声の再配布・販売・公開は厳禁
- Radikoの利用規約を尊重すること
- VPN Gateは学術実験プロジェクトなので、過度な負荷をかけないこと
