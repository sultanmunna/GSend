"""Dev helper: add/list/remove Gmail accounts without the tray app.

`add` opens the browser for the OAuth flow, stores the refresh token in Windows
Credential Manager and the email in accounts.json. Prints account emails only —
never tokens, never mail content (docs/SECURITY.md section 5).

Usage:
    python scripts/dev_add_account.py add
    python scripts/dev_add_account.py list
    python scripts/dev_add_account.py remove someone@gmail.com
"""

from __future__ import annotations

import argparse

from gmail_notifier.accounts import AccountStore
from gmail_notifier.auth import add_account_interactive, remove_account
from gmail_notifier.errors import AuthCancelled, ConfigError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage dev accounts for Gmail Tray Notifier.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("add", help="open the browser and add an account")
    subparsers.add_parser("list", help="list stored account emails")
    remove_parser = subparsers.add_parser("remove", help="remove an account")
    remove_parser.add_argument("email", help="account email to remove")
    args = parser.parse_args(argv)

    store = AccountStore()

    if args.command == "add":
        try:
            email = add_account_interactive()
        except AuthCancelled:
            print("Sign-in cancelled or timed out.")
            return 1
        except ConfigError as exc:
            print(f"Configuration problem: {exc}")
            return 1
        except Exception as exc:
            print(f"Sign-in failed ({type(exc).__name__}).")
            return 1
        store.add(email)
        print(f"Added {email}")
        return 0

    if args.command == "list":
        for account in store.list():
            suffix = f" ({account.label})" if account.label else ""
            print(f"{account.email}{suffix}")
        return 0

    # remove
    store.remove(args.email)
    remove_account(args.email)
    print(f"Removed {args.email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
