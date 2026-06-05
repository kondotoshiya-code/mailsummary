"""Gmail からメールを取得するクライアント。

OAuth2 のリフレッシュトークンを使ってアクセストークンを発行し、
指定した時刻以降に届いた受信トレイのメールを取り出す。
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# 読み取り専用スコープ（メールの送信・削除はできない）
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# 本文として Claude に渡す最大文字数（コスト・トークン節約のため）
MAX_BODY_CHARS = 2500


@dataclass
class Email:
    id: str
    thread_id: str
    sender: str
    subject: str
    date: str
    snippet: str
    body: str
    labels: list[str] = field(default_factory=list)

    @property
    def is_unread(self) -> bool:
        return "UNREAD" in self.labels


class _HTMLTextExtractor(HTMLParser):
    """HTML メールから素のテキストを抜き出す簡易パーサ。"""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip and data.strip():
            self._chunks.append(data)

    def get_text(self) -> str:
        text = " ".join(self._chunks)
        return re.sub(r"\s+", " ", text).strip()


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    return parser.get_text()


def _decode_part(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")


def _extract_body(payload: dict) -> str:
    """payload を再帰的にたどって text/plain（無ければ text/html）を取り出す。"""
    plain: list[str] = []
    html: list[str] = []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if mime == "text/plain" and data:
            plain.append(_decode_part(data))
        elif mime == "text/html" and data:
            html.append(_decode_part(data))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)

    if plain:
        text = "\n".join(plain)
    elif html:
        text = _html_to_text("\n".join(html))
    else:
        text = ""

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > MAX_BODY_CHARS:
        text = text[:MAX_BODY_CHARS] + " …(以下省略)"
    return text


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def build_service(client_id: str, client_secret: str, refresh_token: str):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def fetch_emails(service, after_epoch: int, max_results: int = 40) -> list[Email]:
    """after_epoch（UNIX秒）以降に届いた受信トレイのメールを取得する。

    プロモーション・SNS カテゴリは除外してノイズを減らす。
    """
    query = f"in:inbox after:{after_epoch} -category:promotions -category:social"
    listed = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    messages = listed.get("messages", [])

    emails: list[Email] = []
    for meta in messages:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=meta["id"], format="full")
            .execute()
        )
        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        emails.append(
            Email(
                id=msg["id"],
                thread_id=msg.get("threadId", ""),
                sender=_header(headers, "From"),
                subject=_header(headers, "Subject") or "(件名なし)",
                date=_header(headers, "Date"),
                snippet=msg.get("snippet", ""),
                body=_extract_body(payload),
                labels=msg.get("labelIds", []),
            )
        )
    return emails
