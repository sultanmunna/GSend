"""Dev helper: print the latest mails of one stored account to the console.

Milestone M2 acceptance: shows the latest mails with correct sender names and
subjects, including non-ASCII. Console only — never writes mail data to files
(docs/SECURITY.md section 5).

Usage:
    python scripts/dev_fetch.py [email] [--limit N]
"""

from __future__ import annotations

import argparse

from gmail_notifier.accounts import AccountStore
from gmail_notifier.auth import credentials_for
from gmail_notifier.errors import ConfigError, GmailError, ReauthRequired
from gmail_notifier.gmail_client import GmailClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print the latest mails of one account (dev only)."
    )
    parser.add_argument(
        "email",
        nargs="?",
        default=None,
        help="account email; defaults to the first stored account",
    )
    parser.add_argument("--limit", type=int, default=3, help="how many mails to show (default 3)")
    args = parser.parse_args(argv)

    accounts = AccountStore().list()
    if not accounts:
        print("No accounts stored. Run scripts/dev_add_account.py add first.")
        return 1
    email = args.email or accounts[0].email

    try:
        client = GmailClient(email, credentials_for(email))
        ids = client.latest_inbox_ids(limit=max(1, args.limit), only_primary=False)
        mails = [client.get_mail(message_id) for message_id in ids]
    except ReauthRequired:
        print(f"Sign-in required for {email}; run scripts/dev_add_account.py add.")
        return 1
    except ConfigError as exc:
        print(f"Configuration problem: {exc}")
        return 1
    except GmailError as exc:
        print(f"Gmail fetch failed ({type(exc).__name__}).")
        return 1

    if not mails:
        print("No INBOX mail found.")
        return 0
    for mail in mails:
        state = "unread" if mail.unread else "read  "
        print(f"[{state}] {mail.sender_name} :: {mail.subject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
