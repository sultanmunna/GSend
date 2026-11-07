"""Google OAuth and refresh-token storage.

Installed-app loopback flow with PKCE in the user's browser (DECISIONS D-02).
This is the ONLY module that touches Windows Credential Manager via `keyring`
(hard rule 4): only the refresh token is stored, under service
`config.KEYRING_SERVICE` with the account email as username. Tokens and client
secrets are never logged or put into error messages; account emails appear at
DEBUG level only (docs/SECURITY.md section 5).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import webbrowser
import wsgiref.simple_server
import wsgiref.util
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import keyring
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow, _WSGIRequestHandler

from gmail_notifier import config
from gmail_notifier.errors import AuthCancelled, ConfigError, GmailError, ReauthRequired

try:
    # The library's hardened loopback server: exclusive address binding on
    # Windows plus a ::1 reservation so no other process can intercept the
    # OAuth redirect. Not every supported version ships it; the fallback is
    # still bound to localhost only.
    from google_auth_oauthlib.flow import _ExclusiveWSGIServer as _LoopbackServer
except ImportError:  # pragma: no cover - depends on the installed library version
    _LoopbackServer = wsgiref.simple_server.WSGIServer

logger = logging.getLogger(__name__)

_CLIENT_CONFIG_FILE_NAME = "client_config.json"
_REVOKE_TIMEOUT_SECONDS = 10
_SUCCESS_MESSAGE = "Signed in. You can close this tab."


def load_client_config() -> dict:
    """Load the OAuth client config, in the load order of docs/ARCHITECTURE.md section 5:

    env `GMAIL_NOTIFIER_CLIENT_CONFIG` path, then the bundled resource
    (PyInstaller's `sys._MEIPASS`), then `./client_config.json` for development.
    Raises `ConfigError` when no usable file is found.
    """
    candidates: list[Path] = []
    env_path = os.environ.get("GMAIL_NOTIFIER_CLIENT_CONFIG")
    if env_path:
        candidates.append(Path(env_path))
    bundled_dir = getattr(sys, "_MEIPASS", None)
    if bundled_dir:
        candidates.append(Path(bundled_dir) / _CLIENT_CONFIG_FILE_NAME)
    candidates.append(Path.cwd() / _CLIENT_CONFIG_FILE_NAME)

    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("installed"), dict):
            logger.debug("client config loaded")
            return data
    raise ConfigError(
        "no usable client_config.json found; set GMAIL_NOTIFIER_CLIENT_CONFIG "
        "or place the file next to the app (see docs/GOOGLE_CLOUD_SETUP.md)"
    )


def add_account_interactive(timeout_seconds: int = 180, client_config: dict | None = None) -> str:
    """Run the browser sign-in and store the refresh token; return the account email.

    Blocks until the user finishes in the browser, cancels, or the timeout hits
    (docs/ARCHITECTURE.md section 6). Runs only when called — never at import.
    Raises `AuthCancelled` on cancel/timeout and `GmailError` when Google returns
    no refresh token; in the latter case nothing is stored.
    """
    cfg = client_config if client_config is not None else load_client_config()
    flow = InstalledAppFlow.from_client_config(
        cfg,
        config.SCOPES,
        autogenerate_code_verifier=True,  # PKCE, hard rule 2
    )
    credentials = _run_local_sign_in(flow, timeout_seconds)

    email = _profile_email(credentials)
    refresh_token = getattr(credentials, "refresh_token", None)
    if not refresh_token:
        # prompt=consent + offline access should always yield one; refuse to store None.
        raise GmailError("Google returned no refresh token; nothing was stored")
    keyring.set_password(config.KEYRING_SERVICE, email, refresh_token)
    logger.info("sign-in completed; token stored")
    logger.debug("sign-in completed for %s", email)
    return email


def credentials_for(email: str, client_config: dict | None = None) -> Credentials:
    """Rebuild polling credentials from the stored refresh token.

    The Gmail API service objects stay in the poller thread; this only builds the
    credential. Raises `ReauthRequired` when no token is stored for the account.
    """
    refresh_token = keyring.get_password(config.KEYRING_SERVICE, email)
    if not refresh_token:
        raise ReauthRequired("no stored token for this account; sign in again")
    cfg = client_config if client_config is not None else load_client_config()
    installed = cfg.get("installed")
    if (
        not isinstance(installed, dict)
        or "client_id" not in installed
        or "client_secret" not in installed
    ):
        raise ConfigError("client config is missing client_id/client_secret")
    return Credentials(
        None,
        refresh_token=refresh_token,
        token_uri=installed.get("token_uri", config.GOOGLE_TOKEN_URL),
        client_id=installed["client_id"],
        client_secret=installed["client_secret"],
        scopes=config.SCOPES,
    )


def remove_account(email: str) -> None:
    """Delete the stored token and best-effort revoke it; never raises.

    Revocation failures are logged by type only and ignored (docs/ARCHITECTURE.md
    section 6: revocation failure must not block removal). Removing an account
    without a stored token is a no-op.
    """
    try:
        token = keyring.get_password(config.KEYRING_SERVICE, email)
    except Exception as exc:
        logger.warning("token read failed (%s)", type(exc).__name__)
        token = None
    try:
        keyring.delete_password(config.KEYRING_SERVICE, email)
    except Exception as exc:
        # Also fires when the entry is already gone; removal stays idempotent.
        logger.warning("token delete failed (%s)", type(exc).__name__)
    if token:
        _revoke_token(token)
    logger.info("account removed; token deleted")
    logger.debug("account removed: %s", email)


def has_token(email: str) -> bool:
    """Whether a refresh token is stored for the account; keyring errors count as no."""
    try:
        return keyring.get_password(config.KEYRING_SERVICE, email) is not None
    except Exception as exc:
        logger.warning("token read failed (%s)", type(exc).__name__)
        return False


class _LoopbackApp:
    """WSGI app that shows the success page and captures the redirect URI."""

    def __init__(self, success_message: str) -> None:
        self._success_message = success_message
        self.last_request_uri: str | None = None

    def __call__(
        self,
        environ: dict[str, object],
        start_response: Callable[[str, list[tuple[str, str]]], object],
    ) -> list[bytes]:
        start_response("200 OK", [("Content-type", "text/plain; charset=utf-8")])
        self.last_request_uri = wsgiref.util.request_uri(environ)
        return [self._success_message.encode("utf-8")]


def _run_local_sign_in(flow: InstalledAppFlow, timeout_seconds: int) -> Credentials:
    """Open the browser and wait on a loopback server for the OAuth redirect.

    Not `InstalledAppFlow.run_local_server` on purpose (DECISIONS D-14): the
    library ends its single `handle_request` wait when the browser's first
    connection is aborted mid-handshake — routine on Windows — treats that as
    a timeout (`WSGITimeoutError`, an `AttributeError` subclass) and closes
    the server, so the browser's real redirect is refused. This loop keeps
    waiting until the redirect arrives or `timeout_seconds` elapses.
    """
    app = _LoopbackApp(_SUCCESS_MESSAGE)
    server = wsgiref.simple_server.make_server(
        "localhost",
        0,
        app,
        server_class=_LoopbackServer,
        handler_class=_WSGIRequestHandler,
    )
    try:
        flow.redirect_uri = f"http://localhost:{server.server_port}/"
        auth_url, _state = flow.authorization_url(prompt="select_account consent")
        if not webbrowser.open(auth_url, new=1, autoraise=True):
            logger.warning("browser did not open for sign-in; waiting for the timeout")
        deadline = time.monotonic() + timeout_seconds
        while app.last_request_uri is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AuthCancelled("sign-in timed out or the tab was closed")
            server.timeout = remaining
            server.handle_request()
        # oauthlib insists on https in the authorization response; the redirect was http.
        authorization_response = app.last_request_uri.replace("http", "https", 1)
        flow.fetch_token(authorization_response=authorization_response)
        return flow.credentials
    finally:
        server.server_close()


def _profile_email(credentials: Credentials) -> str:
    """Build a throwaway Gmail service, read the profile email, discard the service."""
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build  # lazy: keeps app startup light

    # google-auth 2.62+ removed Credentials.authorize; AuthorizedHttp from the
    # separate google-auth-httplib2 package is the supported wrapper (D-15).
    http = AuthorizedHttp(credentials, httplib2.Http(timeout=config.HTTP_TIMEOUT_SECONDS))
    service = build("gmail", "v1", http=http, cache_discovery=False)
    try:
        profile = (
            service.users().getProfile(userId="me", fields="emailAddress").execute(num_retries=2)
        )
    finally:
        service.close()
    email = profile.get("emailAddress")
    if not email:
        raise GmailError("Google did not report the account email address")
    return email


def _revoke_token(token: str) -> None:
    """POST the token to Google's revoke endpoint; log failures by type only."""
    data = urlencode({"token": token}).encode("ascii")
    request = Request(
        config.GOOGLE_REVOKE_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urlopen(request, timeout=_REVOKE_TIMEOUT_SECONDS) as response:
            response.read()
    except Exception as exc:
        logger.warning("token revocation failed (%s); ignoring", type(exc).__name__)
