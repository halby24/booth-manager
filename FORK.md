# このフォークについて

[chazmaniandinkle/booth-manager](https://github.com/chazmaniandinkle/booth-manager) の個人用メンテナンスフォークです。
上流の v0.3.0（`b7e3c8c`）は 2026年10月時点の BOOTH ではそのまま動かないため、実機で動作確認しながら最低限の修正を入れています。

上流との差分:

```bash
git fetch upstream
git diff upstream/main..HEAD
```

## 修正内容

上流のコードは BOOTH の旧マークアップ（`booth.pm/orders` の `.orders-item` など）を前提にしており、ログイン後の認証まわりにも不具合がありました。

| # | 症状 | 修正 |
|---|------|------|
| 1 | `booth-auth logout` が `AttributeError: 'Settings' object has no attribute 'get'` で即クラッシュ | `Settings.get()/set()` を追加（`settings.py`） |
| 2 | `booth-auth purchases` が `.orders-item` 待ちでタイムアウト | 購入履歴は `accounts.booth.pm/orders` に移動し、DLリンクは `accounts.booth.pm/library` にしかないため、ライブラリを走査して `.js-download-button` の実URLを取得する実装に変更（`booth_downloader.py`） |
| 3 | ログイン成功後も `booth-auth status` が「未認証」になる | セッションCookieは `_plaza_session_xxxxxx` という名前なので前方一致で判定し、`https://booth.pm/settings` への遷移で最終確認（`browser_auth.py`） |
| 4 | ログイン中にフォーム送信すると `Execution context was destroyed` で中断 | ポーリング中のナビゲーション例外を無視し、タイムアウト時は `/settings` で認証確認するフォールバックを追加 |
| 5 | アイテムフォルダが `BoothItems/8826130_` になる | スクレイプ後のタイトルでフォルダをリネームし、既存フォルダを再利用（`organizer.py`） |
| 6 | VCC自動パッケージが `'folder'` KeyError で失敗 | パッケージ処理にアイテムフォルダを渡す（`organizer.py`） |
| 7 | 404 のアイテムで空フォルダが残る | スクレイプ失敗時に空フォルダを削除して例外を伝播 |
| 8 | ダウンロードが `object NoneType can't be used in 'await' expression` で失敗 | async API の使い方（`set_default_timeout` / `expect_download`）を修正 |

## セットアップ

```bash
git clone git@github.com:halby24/booth-manager.git
cd booth-manager

uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt -e .
.venv/bin/python -m playwright install chromium
```

`playwright install` でブラウザ（約100MB）が `~/Library/Caches/ms-playwright` に入ります。
`HOME` を差し替えて動かす場合は `PLAYWRIGHT_BROWSERS_PATH` の指定が必要です。

## 使い方

```bash
# 認証（Chromiumが開くのでログインする）
.venv/bin/booth-auth login
.venv/bin/booth-auth status

# 購入一覧 / DBへ反映
.venv/bin/booth-auth purchases
.venv/bin/booth-auth purchases --update-db

# ダウンロード（BoothDownloads/{item_id}_{title}/downloads/ に保存）
.venv/bin/booth-auth download --item-id 9070366
.venv/bin/booth-auth download --all --concurrent 2

# アイテムのメタデータ・画像取り込み（CSV / JSON / テキスト）
.venv/bin/booth-assets-manager items.txt

# VCC連携
.venv/bin/booth-vcc enable
.venv/bin/booth-vcc package-all
.venv/bin/booth-vcc status
```

## 動作確認済みの環境

- macOS（Apple Silicon）/ Python 3.12.14 / Playwright 1.64.1
- `login` → `status` → `purchases`（153件）→ `download --item-id`（277MB の zip を取得）
- `booth-assets-manager` でメタデータ・画像・DB登録、CSV/JSON/テキスト入力
- `booth-vcc enable / package-all / validate / status`

## 既知の制限

- `download --all` は購入数に比例して巨大になるため未検証（数百ファイル規模）。
- 「その他のDL方法」の外部配布ファイルは自動DLせず、URLを表示してスキップする。
- 購入日・価格はライブラリ一覧から取得できないため `None` になる。
- VCC リポジトリの生成は確認済みだが、実際の VRChat Creator Companion への追加・Unity へのインストールは未検証（`package.json` の `url` がローカルフォルダを指す形式）。
- DB は `booth_assets_manager/booth.db` に作られる（パッケージ内）。`pip install` をやり直すと消えうるのでバックアップ推奨。
- 上流の `atelier-rewrite` ブランチには取り込んでいない。
