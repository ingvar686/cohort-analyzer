"""Interactively obtain Altegio User Token and save it to .env.

Usage:
  python scripts/auth_user_token.py
  python scripts/auth_user_token.py --login you@email.com

Password is prompted locally and never printed.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from altegio_client import AltegioClient, AltegioError
from env_loader import upsert_env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", help="Altegio login (email/phone)")
    args = parser.parse_args()
    login = args.login or input("Altegio login (email/phone): ").strip()
    password = getpass.getpass("Altegio password: ")
    if not login or not password:
        raise SystemExit("Login and password are required")
    client = AltegioClient()
    try:
        token = client.authorize_user(login, password)
    except AltegioError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc
    upsert_env({"ALTEGIO_USER_TOKEN": token})
    print(
        json.dumps(
            {
                "ok": True,
                "message": "User Token saved to .env",
                "user_token_preview": f"{token[:4]}…{token[-4:]}" if len(token) > 8 else "***",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
