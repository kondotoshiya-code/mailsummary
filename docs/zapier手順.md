# Zapier で「朝昼夕まとめてメールサマリー」を作る手順（コード不要）

プログラミングなしで、Zapier の画面操作だけで作れます。
**Gmail の認証はボタン1つ**（Google Cloud Console もトークン取得も不要）。

## 全体の形：Zap を4つ作る

```
📥 ためる係（Zap①）
   新着メールが来るたびに「箱（Digest）」に入れる
            ↓
📤 送る係（Zap②朝8時 / Zap③昼12時 / Zap④夕方17時）
   箱の中身をまとめて → AIが分類・要約 → Google Chat に投稿 → 箱を空にする
```

- 箱（Digest by Zapier）に入れて、送るときに空にするので **同じメールは1回しか通知されません**
- 1日3回（8/12/17時）に「まとめて1通」の要約が届きます

---

## 事前に用意するもの（2つ）

1. **Zapier アカウント**（https://zapier.com/ ）
   - ※ 後述の「Webhooks」「Digest」「複数ステップ」を使うため、**有料プラン（Starter 以上）が必要**になることが多いです（月20ドル前後）。まずは無料トライアルでOK。
2. **Google Chat の Webhook URL**
   - 通知したい Google Chat スペースを開く →「アプリと連携」→「Webhook」→「Webhook を追加」→ 名前を付けて作成 → 表示された URL を控える
   - 形：`https://chat.googleapis.com/v1/spaces/.../messages?key=...`
3. **AI のキー**（どちらか）
   - Anthropic（Claude）の API キー、または OpenAI の API キー
   - ※ Zapier 内蔵の「AI by Zapier」を使えばキー不要にもできます（精度はやや簡易）

---

## Zap①：ためる係（メールを箱に入れる）

1. Zapier で「Create」→「Zaps」→ 新規作成
2. **Trigger（きっかけ）**：`Gmail` を選び、イベントは **New Email**
   - Gmail アカウント（kondo.toshiya@lm-sg.com）を「Connect」→ Google でサインインするだけ
   - 「Search String」に次を入れるとノイズと費用を減らせます：
     `in:inbox -category:promotions -category:social`
3. **Action（やること）**：`Digest by Zapier` を選び、イベントは **Append Entry to Digest**
   - **Title**：`mail-digest`（好きな名前。送る係と必ず同じにする）
   - **Frequency**：`Manual`（手動で出すので）
   - **Entry**：下のように、差出人・件名・本文を入れる（右の「+」でGmailの項目を差し込む）
     ```
     差出人: {{From}} ／ 件名: {{Subject}}
     本文: {{Body Plain}}
     ---
     ```
4. 「Publish」して Zap①を ON にする

> これで、新しいメールが来るたびに箱（mail-digest）に自動で貯まります。

---

## Zap②：送る係（朝8時）

1. 新しい Zap を作成
2. **Trigger**：`Schedule by Zapier` → **Every Day**
   - 「Time of Day」を **8:00 AM** に設定
   - 「Trigger on weekends?」は Yes（土日も送るなら）
3. **Action 1**：`Digest by Zapier` → **Release Existing Digest**
   - **Title**：`mail-digest`（Zap①と同じ名前）
   - これで箱の中身が出てきて、箱は空になります
4. **Action 2**：AI ステップ（`Anthropic (Claude)` または `ChatGPT (OpenAI)` または `AI by Zapier`）
   - キーを Connect（必要な場合）
   - プロンプト欄に、下の「AIへの指示文」を貼り付け
   - 文中の `{{digest}}` の部分は、右の「+」から **Step 3（Digest）の出力（Digest 本文）** を差し込む
5. **Action 3**：Google Chat に投稿（どちらか）
   - 簡単なのは `Webhooks by Zapier` → **POST**
     - **URL**：控えた Google Chat の Webhook URL
     - **Payload Type**：`json`
     - **Data**：キー `text`、値に **Step 4（AI）の出力** を差し込む
   - または `Google Chat` アプリ → スペースにメッセージ投稿（スペースのメンバー権限が必要）
6. 「Publish」して ON

---

## Zap③（昼12時）・Zap④（夕方17時）

Zap②を **Copy（複製）** して、**Trigger の時刻だけ** 12:00 PM / 5:00 PM に変えればOK。
（Digest の Title は3つとも `mail-digest` のまま＝同じ箱を使う）

---

## AIへの指示文（コピーして貼り付け）

```
あなたは多忙なビジネスパーソンの優秀な秘書です。
以下のメール一覧を読み、3つのカテゴリに分類して日本語で簡潔にまとめてください。
出力はそのまま Google Chat に投稿できる体裁にしてください。広告・自動通知・メルマガなど見る必要のないものは省いてください。

カテゴリの定義:
- 返信すべきメール : 質問・依頼・確認待ち・日程調整など、本人の返事が必要なもの
- 対応すべきメール : 返信ではないが、承認・支払い・手続き・作業など対応が必要なもの
- キャッチアップ   : 返信も対応も不要だが、把握しておくと良い情報

出力フォーマット（このとおりに）:
📬 メールサマリー

✉️ 返信すべきメール
・[件名]（差出人）: 1〜2文の要約。期限があれば明記
（該当なければ「なし」）

✅ 対応すべきメール
・[件名]（差出人）: 1〜2文の要約
（該当なければ「なし」）

📰 キャッチアップ
・[件名]（差出人）: 1〜2文の要約
（該当なければ「なし」）

--- メール一覧 ---
{{digest}}
```

---

## テストのしかた

- Zap①：自分宛にテストメールを送る → 箱に入るか確認
- Zap②：Zapier の編集画面で「Test step」を押すと、その場で Google Chat に届くか試せます
- 本番では、毎日 8/12/17 時に自動で届きます（数分ずれることがあります）

## うまくいかないとき

| 症状 | 対処 |
| --- | --- |
| Chat に届かない | Webhook URL のコピー漏れ／別スペースを見ていないか確認 |
| 同じメールが何度も来る | 送る係の Title が「ためる係」と違う名前になっていないか確認 |
| 箱が空でエラー | その時間帯に新着が無かっただけ。AIステップ前に Filter で「空なら止める」を入れてもよい |
| 費用が気になる | Zap①の Search String を厳しくして対象メールを絞る（重要な人だけ等） |

困ったら、エラー画面の文章を Claude に貼り付けて相談してください。
