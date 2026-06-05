"""メールサマリーのエントリポイント。

Gmail から前回スロット以降のメールを取得 → Claude で分類・要約 →
Google Chat に送信する。GitHub Actions の cron から呼ばれる想定。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import chat_client
import classifier
import gmail_client

# 1日のスケジュール（ローカルタイムの時刻）
SLOT_HOURS = [8, 12, 17]


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"環境変数 {name} が設定されていません。", file=sys.stderr)
        sys.exit(1)
    return value


def determine_slot(now: datetime) -> str:
    """現在時刻に最も近いスロット名を返す。"""
    hour = now.hour
    if hour < 10:
        return "morning"
    if hour < 14:
        return "noon"
    return "evening"


def previous_slot_time(now: datetime) -> datetime:
    """直前のスケジュール時刻を返す。これ以降のメールを集計対象にする。

    朝の実行では前日17時以降（＝夜間＋前日夕方分）をカバーする。
    """
    today_slots = [
        now.replace(hour=h, minute=0, second=0, microsecond=0) for h in SLOT_HOURS
    ]
    # 30分の余裕を持たせ、cron の発火時刻ゆらぎを吸収する
    past = [t for t in today_slots if t <= now - timedelta(minutes=30)]
    if past:
        return past[-1]
    yesterday = now - timedelta(days=1)
    return yesterday.replace(hour=SLOT_HOURS[-1], minute=0, second=0, microsecond=0)


def main() -> None:
    client_id = _require_env("GMAIL_CLIENT_ID")
    client_secret = _require_env("GMAIL_CLIENT_SECRET")
    refresh_token = _require_env("GMAIL_REFRESH_TOKEN")
    anthropic_key = _require_env("ANTHROPIC_API_KEY")
    webhook_url = _require_env("GOOGLE_CHAT_WEBHOOK_URL")

    tz = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Tokyo"))
    model = os.environ.get("ANTHROPIC_MODEL", classifier.DEFAULT_MODEL)
    now = datetime.now(tz)

    # 手動実行などで遡り時間を上書きしたい場合
    override = os.environ.get("LOOKBACK_HOURS")
    if override:
        after_dt = now - timedelta(hours=float(override))
    else:
        after_dt = previous_slot_time(now)

    slot = determine_slot(now)
    after_epoch = int(after_dt.timestamp())

    print(f"[{now.isoformat()}] スロット={slot} 集計対象={after_dt.isoformat()} 以降")

    service = gmail_client.build_service(client_id, client_secret, refresh_token)
    emails = gmail_client.fetch_emails(service, after_epoch)
    print(f"取得メール: {len(emails)}件")

    classifications = classifier.classify_emails(emails, anthropic_key, model=model)

    # ignore は通知しない
    notable = [c for c in classifications if c.category != "ignore"]
    print(
        "分類結果: "
        f"返信={sum(c.category == 'reply' for c in notable)} "
        f"対応={sum(c.category == 'action' for c in notable)} "
        f"キャッチアップ={sum(c.category == 'catchup' for c in notable)} "
        f"（除外 ignore={len(classifications) - len(notable)}）"
    )

    messages = chat_client.build_messages(notable, slot, now.strftime("%Y/%m/%d"))
    chat_client.send(webhook_url, messages)
    print(f"Google Chat へ {len(messages)} メッセージ送信しました。")


if __name__ == "__main__":
    main()
