"""Thin Gmail API wrapper plus pure parsers from API dicts to Mail.

Read-only scope only (hard rule 2). The exact calls, `fields` masks and error
mapping follow docs/ARCHITECTURE.md sections 8 and 9. Service objects are not
thread-safe: create `GmailClient` and use it in one thread only (the poller's).
No mail content ever appears in exception messages — they carry statuses and
error classes only (docs/SECURITY.md section 5).
"""

from __future__ import annotations

import functools
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

import httplib2
from google.auth.exceptions import RefreshError
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from gsend import config, errors, text_utils
from gsend.models import Mail

logger = logging.getLogger(__name__)


class MailSource(Protocol):
    """What the poller needs from a mail source: the real client or a test fake."""

    def latest_inbox_ids(self, limit: int, only_primary: bool) -> list[str]:
        """Return up to `limit` latest INBOX message ids, newest first."""
        ...

    def get_mail(self, message_id: str) -> Mail:
        """Fetch and parse one message (metadata only)."""
        ...


def _build_service(credentials: Any) -> Any:
    """Build the Gmail service with a socket timeout (no unbounded waits).

    `google-auth` 2.62+ removed `Credentials.authorize`; the wrapper from the
    separate `google-auth-httplib2` package does the same job (DECISIONS D-15).
    `static_discovery=True` uses the bundled discovery document instead of
    fetching one from www.googleapis.com at startup, so every request goes to
    the documented allowlist hosts only (DECISIONS D-19).
    """
    http = AuthorizedHttp(credentials, httplib2.Http(timeout=config.HTTP_TIMEOUT_SECONDS))
    return build("gmail", "v1", http=http, cache_discovery=False, static_discovery=True)


def _map_google_errors(func):
    """Translate Google/network exceptions into the app's error types.

    RefreshError -> ReauthRequired; HTTP 429/5xx and network/timeout problems ->
    TransientError; every other HttpError -> GmailError. Exception messages stay
    free of mail content.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        try:
            return func(*args, **kwargs)
        except RefreshError as exc:
            raise errors.ReauthRequired("token expired or revoked; sign in again") from exc
        except HttpError as exc:
            status = getattr(exc, "status", None)
            if status is None:
                status = getattr(getattr(exc, "resp", None), "status", None)
            try:
                status_code = int(status)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                status_code = 0
            if status_code == 429 or status_code >= 500:
                raise errors.TransientError(
                    f"Gmail API transient error (HTTP {status_code})"
                ) from exc
            raise errors.GmailError(f"Gmail API error (HTTP {status_code})") from exc
        except (httplib2.ServerNotFoundError, OSError, TimeoutError) as exc:
            raise errors.TransientError("network error; will retry with backoff") from exc

    return wrapper


def parse_message(account_email: str, api_dict: dict) -> Mail:
    """Pure parser: a Gmail API message dict -> Mail (docs/ARCHITECTURE.md section 4)."""
    headers = _header_map(api_dict.get("payload"))
    sender_name, sender_email = text_utils.parse_sender(headers.get("from", ""))
    subject = text_utils.decode_header_value(headers.get("subject", "")).strip() or "(no subject)"
    return Mail(
        account=account_email,
        id=str(api_dict.get("id", "")),
        thread_id=str(api_dict.get("threadId", "")),
        sender_name=sender_name,
        sender_email=sender_email,
        subject=subject,
        snippet=text_utils.clean_snippet(str(api_dict.get("snippet", ""))),
        received_at=_internal_date_utc(api_dict.get("internalDate")),
        unread="UNREAD" in (api_dict.get("labelIds") or []),
    )


class GmailClient:
    """Gmail API access for one account, implementing MailSource."""

    def __init__(self, account_email: str, credentials: Any, service: Any = None) -> None:
        """`service` is an injection seam for tests; production builds it here."""
        self._account_email = account_email
        self._service = service if service is not None else _build_service(credentials)

    @_map_google_errors
    def latest_inbox_ids(self, limit: int, only_primary: bool) -> list[str]:
        params: dict[str, Any] = {
            "userId": "me",
            "labelIds": ["INBOX"],
            "maxResults": limit,
            "fields": "messages(id,threadId)",
            # googleapiclient drops None params, so no q filter when only_primary is off.
            "q": "category:primary" if only_primary else None,
        }
        response = self._service.users().messages().list(**params).execute(num_retries=2)
        messages = response.get("messages", []) if isinstance(response, dict) else []
        return [m["id"] for m in messages if isinstance(m, dict) and "id" in m]

    @_map_google_errors
    def get_mail(self, message_id: str) -> Mail:
        response = (
            self._service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject"],
                fields="id,threadId,internalDate,labelIds,snippet,payload/headers",
            )
            .execute(num_retries=2)
        )
        return parse_message(self._account_email, response)


def _header_map(payload: Any) -> dict[str, str]:
    """Lower-cased header name -> value, from the payload/headers list."""
    headers = payload.get("headers", []) if isinstance(payload, dict) else []
    result: dict[str, str] = {}
    for entry in headers:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            result[entry["name"].lower()] = str(entry.get("value", ""))
    return result


def _internal_date_utc(internal_ms: Any) -> datetime:
    """internalDate (ms since epoch, string) -> aware UTC datetime.

    A missing or invalid value falls back to the epoch, which can never pass the
    poller's cutoff — a mail without a date must not toast.
    """
    try:
        return datetime.fromtimestamp(int(str(internal_ms)) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return datetime(1970, 1, 1, tzinfo=UTC)
