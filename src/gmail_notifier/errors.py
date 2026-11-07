"""Exception types shared across the app, mapped from lower-level failures.

- `GmailError`: base class for every error this app handles explicitly.
- `ConfigError`: local configuration is missing or unusable.
- `TransientError`: temporary failure (offline, timeout, HTTP 429/5xx); back off and retry.
- `ReauthRequired`: refresh token missing, revoked or expired; sign in again.
- `AuthCancelled`: the OAuth flow was cancelled or timed out before completing.
- `KeyringBackendError`: the OS keyring is not Windows Credential Manager; tokens are refused.
"""

from __future__ import annotations


class GmailError(Exception):
    """Base class for all errors this app handles explicitly."""


class ConfigError(GmailError):
    """Local configuration is missing or unusable (e.g. no client config found)."""


class KeyringBackendError(GmailError):
    """The OS keyring backend is not Windows Credential Manager; storing tokens is refused."""


class TransientError(GmailError):
    """Temporary failure (no internet, timeout, HTTP 429/5xx); retry with backoff."""


class ReauthRequired(GmailError):
    """The stored refresh token is missing, revoked or expired; the user must sign in again."""


class AuthCancelled(GmailError):
    """The OAuth flow was cancelled by the user or timed out."""
