"""分類結果を Google Chat の Incoming Webhook に送信する。

Google Chat の1メッセージあたりのテキスト上限（約4096文字）に収まるよう、
必要に応じて分割送信する。
"""

from __future__ import annotations

import re

import requests

from classifier import Classification

# Google Chat のテキストメッセージ上限に対する安全マージン
MAX_MESSAGE_CHARS = 3800

PRIORITY_MARK = {"high": "🔴", "medium": "🟡", "low": "⚪"}

# カテゴリの表示順・見出し
SECTIONS = [
    ("reply", "✉️ *返信すべきメール*"),
    ("action", "✅ *対応すべきメール*"),
    ("catchup", "📰 *キャッチアップ（把握しておくと良い内容）*"),
]


def _short_sender(sender: str) -> str:
    """'Taro Yamada <taro@example.com>' -> 'Taro Yamada' のように整形。"""
    m = re.match(r"\s*\"?([^\"<]+?)\"?\s*<", sender)
    if m:
        return m.group(1).strip()
    return sender.strip()


def _slot_label(slot: str) -> str:
    return {"morning": "朝", "noon": "昼", "evening": "夕方"}.get(slot, slot)


def build_messages(
    classifications: list[Classification],
    slot: str,
    date_str: str,
) -> list[str]:
    grouped: dict[str, list[Classification]] = {"reply": [], "action": [], "catchup": []}
    for c in classifications:
        if c.category in grouped:
            grouped[c.category].append(c)

    # 優先度の高い順に並べる
    order = {"high": 0, "medium": 1, "low": 2}
    for items in grouped.values():
        items.sort(key=lambda c: order.get(c.priority, 1))

    reply_n = len(grouped["reply"])
    action_n = len(grouped["action"])
    catchup_n = len(grouped["catchup"])

    header = (
        f"*📬 メールサマリー（{_slot_label(slot)}）* — {date_str}\n"
        f"返信 {reply_n}件 / 対応 {action_n}件 / キャッチアップ {catchup_n}件"
    )

    if reply_n == action_n == catchup_n == 0:
        return [header + "\n\n新着で対応が必要なメールはありませんでした。✨"]

    lines: list[str] = [header]
    for key, title in SECTIONS:
        items = grouped[key]
        if not items:
            continue
        lines.append("")
        lines.append(f"{title}（{len(items)}件）")
        for c in items:
            mark = PRIORITY_MARK.get(c.priority, "🟡")
            sender = _short_sender(c.email.sender)
            deadline = f" 〆{c.deadline}" if c.deadline else ""
            lines.append(f"{mark} *{c.email.subject}*（{sender}）{deadline}")
            lines.append(f"　{c.summary}")

    return _split_into_messages(lines)


def _split_into_messages(lines: list[str]) -> list[str]:
    messages: list[str] = []
    current: list[str] = []
    length = 0
    for line in lines:
        add = len(line) + 1
        if length + add > MAX_MESSAGE_CHARS and current:
            messages.append("\n".join(current))
            current = []
            length = 0
        current.append(line)
        length += add
    if current:
        messages.append("\n".join(current))
    return messages


def send(webhook_url: str, messages: list[str]) -> None:
    for text in messages:
        resp = requests.post(
            webhook_url,
            json={"text": text},
            headers={"Content-Type": "application/json; charset=UTF-8"},
            timeout=30,
        )
        resp.raise_for_status()
