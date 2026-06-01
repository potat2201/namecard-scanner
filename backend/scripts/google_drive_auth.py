#!/usr/bin/env python3
"""One-time Google Drive OAuth setup for personal Gmail accounts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import settings
from app.google_drive import SCOPES, _oauth_client_path, _save_oauth_token, oauth_token_path


def main() -> None:
    client_path = _oauth_client_path()
    if not client_path:
        print("Error: set GOOGLE_DRIVE_OAUTH_CLIENT_PATH in .env to your OAuth client JSON.")
        print("Create one in Google Cloud Console → Credentials → OAuth client ID → Desktop app.")
        raise SystemExit(1)

    import json

    client_data = json.loads(client_path.read_text(encoding="utf-8"))
    if "installed" not in client_data and "web" in client_data:
        print("Error: your JSON is a Web application client, not a Desktop app.")
        print("InstalledAppFlow requires Desktop app credentials.")
        print("")
        print("Fix in Google Cloud Console → Credentials:")
        print("  1. Create credentials → OAuth client ID → Application type: Desktop app")
        print("  2. Download the new JSON (it should contain an \"installed\" key, not \"web\")")
        print(f"  3. Replace {client_path}")
        raise SystemExit(1)

    print(f"Using OAuth client: {client_path}")
    print("A browser window will open. Sign in with the Google account that owns your Drive.")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), list(SCOPES))
    creds = flow.run_local_server(port=0)
    _save_oauth_token(creds)
    print(f"Saved token to: {oauth_token_path()}")
    print("Restart the backend and upload a name card to test.")


if __name__ == "__main__":
    main()
