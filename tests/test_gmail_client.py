"""Tests for gmail_client: pure parsing from JSON fixtures, exact API params, error mapping.

All offline: the service is faked, no network, no real Google calls.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httplib2
import pytest
from google.auth.exceptions import RefreshError
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.errors import HttpError

from gsend import config, gmail_client
from gsend.errors import GmailError, ReauthRequired, TransientError
from gsend.gmail_client import GmailClient, parse_message
from gsend.models import Mail

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


# --- fake Gmail service -------------------------------------------------------


class FakeRequest:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def execute(self, num_retries=0):
        assert num_retries == 2, "Gmail API calls must pass num_retries=2"
        if self._error is not None:
            raise self._error
        return self._result


class FakeMessages:
    def __init__(self):
        self.list_kwargs = None
        self.get_kwargs = None
        self.list_result = {}
        self.get_result = {}
        self.list_error = None
        self.get_error = None

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return FakeRequest(self.list_result, self.list_error)

    def get(self, **kwargs):
        self.get_kwargs = kwargs
        return FakeRequest(self.get_result, self.get_error)


class FakeUsers:
    def __init__(self, messages):
        self._messages = messages

    def messages(self):
        return self._messages


class FakeService:
    def __init__(self):
        self.messages = FakeMessages()
        self._users = FakeUsers(self.messages)

    def users(self):
        return self._users


def make_client(service: FakeService) -> GmailClient:
    return GmailClient("user@example.com", credentials=None, service=service)


# --- parse_message (pure) -----------------------------------------------------


def test_parse_bangla_encoded_headers():
    mail = parse_message("user@example.com", load_fixture("message_bangla.json"))
    assert mail.account == "user@example.com"
    assert mail.id == "msg-bangla"
    assert mail.thread_id == "thread-bangla"
    assert mail.sender_name == "রফিক ইসলাম"
    assert mail.sender_email == "rafik@example.com"
    assert mail.subject == "আজ সন্ধ্যায় মিটিং"
    assert mail.snippet == "'Dinner' at 8pm & more details inside"
    assert mail.unread is True
    assert mail.received_at == datetime.fromtimestamp(1730000000, tz=UTC)


def test_parse_missing_subject_and_read_mail():
    mail = parse_message("user@example.com", load_fixture("message_no_subject.json"))
    assert mail.subject == "(no subject)"
    assert mail.unread is False
    assert mail.sender_name == "Doe, Jane"
    assert mail.sender_email == "jane@example.com"


def test_parse_no_display_name():
    mail = parse_message("user@example.com", load_fixture("message_no_display_name.json"))
    assert mail.sender_name == "noone@nowhere.org"
    assert mail.sender_email == "noone@nowhere.org"
    assert mail.subject == "Weekly report"
    assert mail.unread is True


def test_parse_missing_internal_date_falls_back_to_epoch():
    data = load_fixture("message_no_display_name.json")
    del data["internalDate"]
    mail = parse_message("user@example.com", data)
    # The epoch can never pass the poller's cutoff, so such a mail never toasts.
    assert mail.received_at == datetime(1970, 1, 1, tzinfo=UTC)


def test_parse_minimal_dict_is_tolerant():
    mail = parse_message("user@example.com", {})
    assert isinstance(mail, Mail)
    assert mail.subject == "(no subject)"
    assert mail.unread is False
    assert mail.snippet == ""


# --- GmailClient against a fake service ---------------------------------------


def test_latest_inbox_ids_returns_ids_and_sends_exact_params():
    service = FakeService()
    client = make_client(service)
    service.messages.list_result = load_fixture("list_response.json")
    ids = client.latest_inbox_ids(limit=3, only_primary=True)
    assert ids == ["msg-bangla", "msg-nosubject", "msg-noname"]
    assert service.messages.list_kwargs == {
        "userId": "me",
        "labelIds": ["INBOX"],
        "maxResults": 3,
        "fields": "messages(id,threadId)",
        "q": "category:primary",
    }


def test_latest_inbox_ids_without_primary_has_no_q():
    service = FakeService()
    service.messages.list_result = {"messages": []}
    client = make_client(service)
    assert client.latest_inbox_ids(limit=5, only_primary=False) == []
    assert service.messages.list_kwargs["q"] is None


def test_latest_inbox_ids_handles_empty_response():
    service = FakeService()
    service.messages.list_result = {}
    client = make_client(service)
    assert client.latest_inbox_ids(limit=3, only_primary=True) == []


def test_get_mail_sends_exact_params_and_parses():
    service = FakeService()
    service.messages.get_result = load_fixture("message_bangla.json")
    client = make_client(service)
    mail = client.get_mail("msg-bangla")
    assert service.messages.get_kwargs == {
        "userId": "me",
        "id": "msg-bangla",
        "format": "metadata",
        "metadataHeaders": ["From", "Subject"],
        "fields": "id,threadId,internalDate,labelIds,snippet,payload/headers",
    }
    assert mail.account == "user@example.com"
    assert mail.subject == "আজ সন্ধ্যায় মিটিং"


def test_service_is_built_with_expected_args(monkeypatch):
    recorded = {}

    class FakeCredentials:
        """google_auth_httplib2 stores the credentials; no methods needed."""

    def fake_build(api, version, **kwargs):
        recorded["api"] = api
        recorded["version"] = version
        recorded.update(kwargs)
        return FakeService()

    monkeypatch.setattr(gmail_client, "build", fake_build)
    GmailClient("user@example.com", credentials=FakeCredentials())
    assert recorded["api"] == "gmail"
    assert recorded["version"] == "v1"
    assert recorded["cache_discovery"] is False
    # Every Gmail request must carry a socket timeout (M8 hardening). Since
    # google-auth 2.62 removed Credentials.authorize, the wrapper is
    # google_auth_httplib2.AuthorizedHttp around a timeout-configured Http (D-15).
    http = recorded["http"]
    assert isinstance(http, AuthorizedHttp)
    assert isinstance(http.http, httplib2.Http)
    assert http.http.timeout == config.HTTP_TIMEOUT_SECONDS


# --- error mapping ------------------------------------------------------------


def make_client_with_list_error(error):
    service = FakeService()
    service.messages.list_error = error
    return make_client(service)


def make_client_with_get_error(error):
    service = FakeService()
    service.messages.get_error = error
    return make_client(service)


def test_refresh_error_maps_to_reauth():
    client = make_client_with_list_error(RefreshError("invalid_grant"))
    with pytest.raises(ReauthRequired):
        client.latest_inbox_ids(limit=1, only_primary=True)


def test_http_429_maps_to_transient():
    client = make_client_with_list_error(HttpError(httplib2.Response({"status": 429}), b""))
    with pytest.raises(TransientError) as excinfo:
        client.latest_inbox_ids(limit=1, only_primary=True)
    assert "429" in str(excinfo.value)


def test_http_503_maps_to_transient():
    client = make_client_with_list_error(HttpError(httplib2.Response({"status": 503}), b""))
    with pytest.raises(TransientError):
        client.latest_inbox_ids(limit=1, only_primary=True)


def test_http_403_maps_to_gmail_error():
    client = make_client_with_list_error(HttpError(httplib2.Response({"status": 403}), b""))
    with pytest.raises(GmailError):
        client.latest_inbox_ids(limit=1, only_primary=True)


def test_server_not_found_maps_to_transient_on_get():
    client = make_client_with_get_error(httplib2.ServerNotFoundError("no dns"))
    with pytest.raises(TransientError):
        client.get_mail("msg-1")


def test_oserror_maps_to_transient():
    client = make_client_with_list_error(OSError("connection reset"))
    with pytest.raises(TransientError):
        client.latest_inbox_ids(limit=1, only_primary=True)


def test_error_messages_carry_no_mail_content():
    client = make_client_with_list_error(HttpError(httplib2.Response({"status": 403}), b""))
    with pytest.raises(GmailError) as excinfo:
        client.latest_inbox_ids(limit=1, only_primary=True)
    message = str(excinfo.value)
    assert "Weekly report" not in message
    assert "রফিক" not in message
    assert "msg-bangla" not in message


def test_service_build_uses_bundled_discovery(monkeypatch):
    """The discovery document must come from the bundle, not www.googleapis.com
    (D-19): every network contact stays on the documented allowlist hosts."""
    captured: dict = {}

    def fake_build(*args, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("gsend.gmail_client.build", fake_build)
    gmail_client._build_service(credentials=None)
    assert captured.get("static_discovery") is True
    assert captured.get("cache_discovery") is False


def test_profile_service_build_uses_bundled_discovery(monkeypatch):
    """Same rule for the throwaway profile service in auth.py (D-19)."""
    captured: dict = {}

    def fake_build(*_args, **kwargs):
        captured.update(kwargs)

        class FakeService:
            def users(self):
                return self

            def getProfile(self, **_kw):
                return self

            def execute(self, **_kw):
                return {"emailAddress": "user@example.com"}

            def close(self):
                pass

        return FakeService()

    monkeypatch.setattr("googleapiclient.discovery.build", fake_build)
    from gsend import auth

    email = auth._profile_email(credentials=None)
    assert email == "user@example.com"
    assert captured.get("static_discovery") is True
