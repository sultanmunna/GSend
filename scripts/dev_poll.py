"""Dev harness: run the poller against the real accounts and print new-mail events.

Milestone M3 acceptance: prints no mail events at startup (the baseline is
silent), prints one line per new mail within one poll interval, and survives
offline/online changes. Console only — mail content is never written to files
(docs/SECURITY.md section 5).

Usage: python scripts/dev_poll.py   (Ctrl+C to stop)
"""

from __future__ import annotations

import threading

from gmail_notifier.accounts import AccountStore
from gmail_notifier.auth import credentials_for
from gmail_notifier.gmail_client import GmailClient
from gmail_notifier.poller import Poller
from gmail_notifier.settings import load as load_settings
from gmail_notifier.state import AppState


def main() -> int:
    accounts = AccountStore().list()
    if not accounts:
        print("No accounts stored. Run scripts/dev_add_account.py add first.")
        return 1
    known = [a.email for a in accounts]

    def client_factory(email: str) -> GmailClient:
        return GmailClient(email, credentials_for(email))

    def on_new_mails(email: str, mails: list) -> None:
        number = known.index(email) + 1 if email in known else 0
        for mail in mails:
            print(f"NEW MAIL for account#{number}: {mail.sender_name} :: {mail.subject}")

    def on_reauth_needed(email: str) -> None:
        print(f"SIGN-IN NEEDED for account {email}; run scripts/dev_add_account.py add.")

    state = AppState()
    poller = Poller(
        client_factory=client_factory,
        account_store=AccountStore(),
        state=state,
        settings=load_settings(),
        on_new_mails=on_new_mails,
        on_reauth_needed=on_reauth_needed,
    )
    print(f"Polling {len(accounts)} account(s); new-mail events appear below. Ctrl+C stops.")
    thread = threading.Thread(target=poller.run, name="poller", daemon=True)
    thread.start()
    try:
        while thread.is_alive():
            thread.join(timeout=1)
    except KeyboardInterrupt:
        pass
    finally:
        poller.stop()
        thread.join(timeout=5)
        print("Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
