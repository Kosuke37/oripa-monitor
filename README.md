# Japan Toreca オリパ通知

`japan-toreca.com` のオリパページを5分ごとに監視して、指定価格のガチャの「売り切れ」「新規出品」をLINEに通知します。

## 監視対象の追加・変更は `watches.json` を編集するだけ

リポジトリの **`watches.json` をブラウザ上で編集** → コミット、これだけで反映されます。Pythonを触る必要も、git push する必要もありません。

```json
{
  "watches": [
    {
      "label": "ワンピース",
      "url": "https://japan-toreca.com/oripa/onepiece",
      "prices": [933]
    },
    {
      "label": "ホビー",
      "url": "https://japan-toreca.com/oripa/hobby",
      "prices": [1020, 1030, 1040]
    }
  ]
}
```

各エントリは:
- **label** — 通知に表示される名前(自由)
- **url** — オリパ一覧ページのURL
- **prices** — 監視したい価格(整数の配列、何個でもOK)

### ブラウザだけで監視対象を追加する手順

1. GitHub のリポジトリで `watches.json` をクリック
2. 右上の **鉛筆アイコン(Edit this file)** をクリック
3. JSONを編集(例: ポケモンの500コインを追加)
4. ページ下部の緑のボタン **「Commit changes」** をクリック
5. **5分以内の次回ランから自動反映** ✨

例: ポケモンの500コインも監視に追加したい場合:

```json
{
  "watches": [
    {"label": "ワンピース", "url": "https://japan-toreca.com/oripa/onepiece", "prices": [933]},
    {"label": "ホビー", "url": "https://japan-toreca.com/oripa/hobby", "prices": [1020, 1030, 1040]},
    {"label": "ポケモン", "url": "https://japan-toreca.com/oripa/pokemon", "prices": [500]}
  ]
}
```

JSONの書式を間違えてもデフォルト設定で動き続けるので壊れません。エラーは Actions タブのログで確認できます。

### 主要カテゴリのURL一覧(コピペ用)

| カテゴリ | URL |
|---|---|
| ポケモン | `https://japan-toreca.com/oripa/pokemon` |
| ワンピース | `https://japan-toreca.com/oripa/onepiece` |
| ホビー | `https://japan-toreca.com/oripa/hobby` |
| マイル | `https://japan-toreca.com/oripa/mileage` |
| ドラゴンボール | `https://japan-toreca.com/oripa/dragonball_fw` |
| 遊戯王 | `https://japan-toreca.com/oripa/yugioh` |
| MTG | `https://japan-toreca.com/oripa/mtg` |
| ヴァイス | `https://japan-toreca.com/oripa/ws_tcg` |
| デュエマ | `https://japan-toreca.com/oripa/duel_masters` |
| その他 | `https://japan-toreca.com/oripa/others` |

---

## 通知される2つのイベント

| イベント | 通知例 |
|---|---|
| 🎴 **売り切れ** | 対象ガチャが「残り0/N」になった、または一覧から消えた(完売済みに移動) |
| 🆕 **新規出品** | 過去にない対象価格のガチャが一覧に出てきた(再販を含む) |

販売ごとにガチャIDが変わる仕様なので価格で継続追跡しています。ウタの933ガチャや、次のホビー1020ガチャなどが再販されれば自動的に追跡開始 → 売り切れタイミングでも通知が飛びます。

通知メッセージの例:
```
🎴 [ホビー] 1030コイン/1回 売り切れ
「マリオテニスフィーバー」(id=64371)
残り 0 / 100
https://japan-toreca.com/oripa/hobby
```

```
🆕 [ワンピース] 933コイン/1回 新規出品
「ウタの歌声オリパ」(id=80000)
残り 100/100
https://japan-toreca.com/oripa/onepiece/80000
```

通知の `[ホビー]` 部分は `watches.json` の `label` がそのまま入るので、自分が区別しやすい名前にしてOK(例:「お気に入り」「監視中ロット」など)。

---

## 仕組み

- 実行環境: GitHub Actions(5分ごと・無料)
- 通知: LINE Messaging API(broadcast)
- ページ取得: requests + BeautifulSoup(高速、SSR利用)、必要時のみPlaywrightフォールバック
- 状態保存: `state.json` をリポジトリに自動コミット(重複通知防止)
- 古いエントリは消失から14日後に自動クリーンアップ

---

## セットアップ手順(初回のみ、15分くらい)

### ステップ1: LINE Bot を作る

1. [LINE Developers Console](https://developers.line.biz/console/) にログイン
2. **「新規プロバイダー作成」** → 適当な名前(例: `oripa-notifier`)
3. プロバイダーをクリック → **「新規チャネル作成」** → **「Messaging API」** を選択
4. 必要事項を入力して作成
5. 作成したチャネルを開き、**Messaging API** タブを開く
   - 最下部の **チャネルアクセストークン(長期)** で **「発行」** → 表示されたトークンをコピー
   - 表示されているQRコードを自分のLINEで読み取って **Botを友だち追加**
6. 同じタブで「応答メッセージ」「あいさつメッセージ」を **OFF**(任意)

### ステップ2: GitHub にリポジトリを作る

1. GitHubで新しいリポジトリを作る(**Public 推奨**)
2. このフォルダ一式を push:
   ```bash
   cd oripa_monitor
   git init
   git add .
   git commit -m "initial"
   git branch -M main
   git remote add origin https://github.com/<your-name>/<repo>.git
   git push -u origin main
   ```

### ステップ3: シークレット登録

リポジトリの **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | ステップ1でコピーしたトークン |

### ステップ4: Workflow 権限の確認

**Settings → Actions → General → Workflow permissions** で **Read and write permissions** を選択 → Save

### ステップ5: 動作確認

**Actions** タブ → 左の `Check Oripa Sold Out` → 右上 **「Run workflow」** で手動実行。

- **初回**: 通知なしで、現在出ている対象ガチャを「既知」として記録するだけ
- **2回目以降**: 売り切れ/新規出品 が発生した瞬間にLINE通知

---

## ローカルで先にテスト(任意)

```bash
cd oripa_monitor
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# (1) LINE疎通テスト
export LINE_CHANNEL_ACCESS_TOKEN="xxxxx"
python check.py --notify
# → LINEに「✅ LINE疎通テスト」が届けばOK

# (2) ページ検知テスト(通知も保存もしない)
python check.py --test
# → コンソールに各ページの対象ガチャ一覧が出ます
```

---

## 注意点

### GitHub Actions の月間利用枠

- **Public repo**: 無制限 ✅
- **Private repo**: 無料枠 2,000分/月、5分間隔だと足りない可能性

→ **Public repo を推奨**。トークンはSecretsで管理しているのでコード公開で問題なし。

### 5分間隔は最短であって保証ではない

GitHub Actions の cron は混雑時5〜15分遅延する場合があります。

### LINE Messaging API の月間メッセージ数

無料プラン: **200通/月**(2025年改定)。

### watches.json を編集したのに反映されない

- JSON構文エラーの可能性 → Actionsログを確認(`[ERROR] JSON構文エラー...` が出てるはず)
- 次回ラン(5分後)まで待つ必要あり → Actions タブから手動実行で即時反映可

---

## ファイル構成

```
oripa_monitor/
├── .github/workflows/check.yml   # GitHub Actions 設定
├── check.py                      # メインスクリプト(編集不要)
├── watches.json                  # ← 監視対象の設定(ここを編集)
├── requirements.txt
├── state.json                    # 状態保存(自動更新)
├── .gitignore
└── README.md
```
