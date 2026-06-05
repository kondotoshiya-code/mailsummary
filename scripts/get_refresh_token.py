"""Gmail 読み取り用の OAuth2 リフレッシュトークンを取得するヘルパー。

ローカルの PC で一度だけ実行する。ブラウザが開いて Google アカウントへの
同意を求められ、完了するとリフレッシュトークンが表示される。
その値を GitHub Secrets の GMAIL_REFRESH_TOKEN に登録する。

事前準備:
  1. Google Cloud Console で OAuth クライアント（デスクトップアプリ）を作成
  2. ダウンロードした JSON を credentials.json として本ファイルと同じ場所に置く
  3. pip install google-auth-oauthlib
  4. python get_refresh_token.py
"""

from __future__ import annotations

import os

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    creds_path = os.path.join(here, "credentials.json")
    if not os.path.exists(creds_path):
        raise SystemExit(
            "credentials.json が見つかりません。Google Cloud Console で作成した\n"
            "OAuth クライアント（デスクトップアプリ）の JSON をこの場所に置いてください。"
        )

    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    # access_type=offline かつ prompt=consent でリフレッシュトークンを確実に得る
    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
    )

    with open(creds_path) as f:
        import json

        data = json.load(f)
    client = data.get("installed") or data.get("web") or {}

    print("\n================ 取得結果 ================")
    print("以下を GitHub Secrets に登録してください:\n")
    print(f"GMAIL_CLIENT_ID     = {client.get('client_id', '')}")
    print(f"GMAIL_CLIENT_SECRET = {client.get('client_secret', '')}")
    print(f"GMAIL_REFRESH_TOKEN = {creds.refresh_token}")
    print("=========================================")


if __name__ == "__main__":
    main()
