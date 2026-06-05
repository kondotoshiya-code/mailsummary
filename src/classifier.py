"""Claude API でメールを分類・要約する。

各メールを次の4カテゴリのいずれかに振り分け、日本語の一言要約を付ける。
  - reply   : 返信すべきメール
  - action  : （返信ではなく）対応・作業が必要なメール
  - catchup : 把握しておくべき情報。返信・対応は不要
  - ignore  : 通知・宣伝など、特に見る必要のないもの
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from anthropic import Anthropic

from gmail_client import Email

# 分類に使うモデル。安価で高速な Haiku を既定にする。
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

VALID_CATEGORIES = {"reply", "action", "catchup", "ignore"}

SYSTEM_PROMPT = """\
あなたは多忙なビジネスパーソンの優秀な秘書です。
受信したメール一覧を読み、各メールを次の4カテゴリに分類し、日本語で簡潔に要約します。

カテゴリの定義:
- "reply"  : 本人が「返信」すべきメール（質問・依頼・確認待ち・日程調整など、人からの返事待ち）
- "action" : 返信ではないが本人の「対応・作業」が必要なメール（タスク、承認、支払い、期限のある手続きなど）
- "catchup": 返信も対応も不要だが「把握」しておくべき情報（社内連絡、議事録、ニュース、進捗共有など）
- "ignore" : 広告・宣伝・自動通知・メルマガなど、特に見る必要のないもの

判断のポイント:
- 自分宛に明確なアクションを求めているか
- 期限や緊急度はあるか
- 差出人が重要人物か（上司・顧客・取引先など）

必ず指定された JSON 形式だけを出力してください。前置きや説明文は不要です。"""

USER_PROMPT_TEMPLATE = """\
以下は受信メールの一覧です。それぞれを分類・要約してください。

各メールについて、次のフィールドを持つオブジェクトを作ってください:
- "index"    : メールの番号（入力と同じ整数）
- "category" : "reply" / "action" / "catchup" のいずれか（"ignore" は除外せず必ず付与）
- "summary"  : 日本語で1〜2文の要約（何の用件か、何を求められているか）
- "priority" : "high" / "medium" / "low"（緊急度・重要度）
- "deadline" : 期限が読み取れれば日付や期日、なければ空文字

出力は次の JSON 形式のみ:
{{"items": [{{"index": 0, "category": "reply", "summary": "...", "priority": "high", "deadline": ""}}, ...]}}

--- メール一覧 ---
{emails}
"""


@dataclass
class Classification:
    email: Email
    category: str
    summary: str
    priority: str
    deadline: str


def _format_emails(emails: list[Email]) -> str:
    blocks = []
    for i, e in enumerate(emails):
        body = e.body or e.snippet
        blocks.append(
            f"[{i}]\n"
            f"差出人: {e.sender}\n"
            f"件名: {e.subject}\n"
            f"日時: {e.date}\n"
            f"本文抜粋:\n{body}\n"
        )
    return "\n".join(blocks)


def _parse_json(text: str) -> dict:
    text = text.strip()
    # ```json ... ``` で囲まれている場合に備えて中身を取り出す
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def classify_emails(
    emails: list[Email],
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> list[Classification]:
    if not emails:
        return []

    client = Anthropic(api_key=api_key)
    prompt = USER_PROMPT_TEMPLATE.format(emails=_format_emails(emails))

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(block.text for block in message.content if block.type == "text")

    try:
        data = _parse_json(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Claude の出力を JSON として解釈できませんでした: {exc}\n出力: {raw[:500]}")

    by_index = {item.get("index"): item for item in data.get("items", [])}

    results: list[Classification] = []
    for i, email in enumerate(emails):
        item = by_index.get(i, {})
        category = item.get("category", "catchup")
        if category not in VALID_CATEGORIES:
            category = "catchup"
        results.append(
            Classification(
                email=email,
                category=category,
                summary=item.get("summary", email.subject),
                priority=item.get("priority", "medium"),
                deadline=item.get("deadline", ""),
            )
        )
    return results
