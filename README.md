# mailsummary

Gmail を定期的に読み取り、**返信すべきメール / 対応すべきメール / キャッチアップ用の要約**に分類して、
毎日 **朝8時・昼12時・夕方17時（JST）** に Google Chat へ自動送信するツールです。

- 定期実行: **GitHub Actions の cron**（サーバー不要・無料枠で動作）
- 分類・要約: **Claude API**（既定は `claude-haiku-4-5-20251001`）
- メール取得: **Gmail API**（OAuth2 リフレッシュトークン / 読み取り専用スコープ）
- 送信先: **Google Chat の Incoming Webhook**

## 仕組み

```
GitHub Actions (cron 8/12/17時 JST)
        │
        ▼
   src/main.py
        ├─ gmail_client.py … 前回スロット以降の受信トレイのメールを取得
        ├─ classifier.py  … Claude が reply / action / catchup / ignore に分類＋要約
        └─ chat_client.py … 見出し付きで整形し Google Chat へ送信
```

各実行は「前回のスケジュール時刻以降」に届いたメールを対象にします（朝の実行は前日17時以降をカバー）。
そのため同じメールが繰り返し通知されることはありません。

## 送信メッセージのイメージ

```
📬 メールサマリー（朝） — 2026/06/05
返信 2件 / 対応 1件 / キャッチアップ 3件

✉️ 返信すべきメール（2件）
🔴 来週の打合せ日程について（山田太郎） 〆6/6
　 候補日3つのうち都合の良い日を返信してほしい、との依頼。
...

✅ 対応すべきメール（1件）
🟡 経費精算の差し戻し（経理部）
　 領収書の添付漏れ。再提出が必要。

📰 キャッチアップ（把握しておくと良い内容）（3件）
⚪ 月次レポート共有（企画部）
　 5月の売上は前月比+8%。詳細は添付資料参照。
```

## セットアップ

### 1. Gmail の OAuth2 認証情報を用意する

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
2. 「API とサービス」→「ライブラリ」で **Gmail API** を有効化
3. 「OAuth 同意画面」を設定（内部 / 外部いずれか。テスト中はテストユーザーに自分を追加）
4. 「認証情報」→「認証情報を作成」→「OAuth クライアント ID」→ 種類は **デスクトップアプリ**
5. 作成した JSON をダウンロードし、`scripts/credentials.json` として保存

### 2. リフレッシュトークンを取得する（ローカルで一度だけ）

```bash
pip install google-auth-oauthlib
python scripts/get_refresh_token.py
```

ブラウザで自分の Gmail アカウント（kondo.toshiya@lm-sg.com）で同意すると、
`GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` / `GMAIL_REFRESH_TOKEN` が表示されます。

> ⚠️ `credentials.json` とトークンは秘密情報です。`.gitignore` 済みなのでコミットされません。

### 3. Google Chat の Webhook を用意する

1. 通知を受け取りたい Google Chat の **スペース** を開く
2. スペース名 →「アプリと連携」→「Webhook」→「Webhook を追加」
3. 名前（例: メールサマリー）を付けて作成し、表示された **Webhook URL** をコピー

### 4. Claude API キーを用意する

[Anthropic Console](https://console.anthropic.com/) で API キーを発行します。

### 5. GitHub Secrets を登録する

リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で以下を登録:

| Secret 名 | 値 |
| --- | --- |
| `GMAIL_CLIENT_ID` | 手順2で表示された値 |
| `GMAIL_CLIENT_SECRET` | 手順2で表示された値 |
| `GMAIL_REFRESH_TOKEN` | 手順2で表示された値 |
| `ANTHROPIC_API_KEY` | 手順4の API キー |
| `GOOGLE_CHAT_WEBHOOK_URL` | 手順3の Webhook URL |

### 6. 動作確認

GitHub の **Actions タブ → Mail Summary → Run workflow** で手動実行できます。
`何時間前まで遡るか` に例えば `24` を入れると、直近24時間のメールでテストできます。

問題なければ、あとは cron で毎日 8/12/17 時（JST）に自動送信されます。

## ローカルでの実行

```bash
pip install -r requirements.txt
cp .env.example .env   # 値を埋める
set -a; source .env; set +a
python src/main.py
```

## スケジュールの変更

`.github/workflows/summary.yml` の `cron` を編集します（**UTC 基準**な点に注意）。
JST から UTC へは9時間引きます。例: JST 9:00 → UTC 0:00 → `0 0 * * *`。

## カスタマイズの勘所

- 分類の基準: `src/classifier.py` の `SYSTEM_PROMPT`
- 取得対象メール（フィルタ）: `src/gmail_client.py` の `fetch_emails` 内のクエリ
- メッセージの見た目: `src/chat_client.py`
- 使用モデル: Secrets/環境変数 `ANTHROPIC_MODEL`、または `classifier.DEFAULT_MODEL`

## 注意事項

- GitHub Actions の cron は混雑時に数分〜十数分遅延することがあります（仕様）。
- Gmail スコープは `gmail.readonly` のみ。メールの送信・削除・改変は行いません。
