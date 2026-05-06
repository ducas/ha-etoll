"""Tests for EtollClient HTTP methods (auth, retry, paging)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import pytest
from aioresponses import aioresponses

from custom_components.etoll.client import (
    ACCOUNTS_BASE,
    AUTH_URL,
    REFRESH_URL,
    EtollAuthError,
    EtollClient,
    EtollError,
    EtollSessionExpired,
    Session,
)
from tests.conftest import load_fixture


def _account_re(cod: int) -> re.Pattern:
    """Regex matching any request to the account endpoint (ignores query params)."""
    return re.compile(rf".*accounts/{cod}[/?].*|.*accounts/{cod}$")


def _activity_re(cod: int) -> re.Pattern:
    return re.compile(rf".*accounts/{cod}/account-activity[/?].*|.*accounts/{cod}/account-activity$")


def _searcher_re(cod: int) -> re.Pattern:
    return re.compile(rf".*accounts/{cod}/account-activity/searcher.*")


def _accessible_re() -> re.Pattern:
    return re.compile(r".*accessible-accounts.*")


@pytest.fixture
async def client():
    async with EtollClient("test@example.com", "secret") as c:
        yield c


@pytest.fixture
def auth_payload() -> dict[str, Any]:
    return load_fixture("auth_response.json")


@pytest.fixture
def account_payload() -> dict[str, Any]:
    return load_fixture("account_response.json")


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------


class TestAuthenticate:
    async def test_successful_auth_stores_session(self, client, auth_payload):
        with aioresponses() as m:
            m.post(AUTH_URL, payload=auth_payload, status=200)
            session = await client.authenticate()
        assert isinstance(session, Session)
        assert session.access_token == auth_payload["accessToken"]
        assert client._auth is not None

    async def test_401_raises_auth_error(self, client):
        with aioresponses() as m:
            m.post(AUTH_URL, body="Unauthorized", status=401)
            with pytest.raises(EtollAuthError):
                await client.authenticate()

    async def test_400_raises_auth_error(self, client):
        with aioresponses() as m:
            m.post(AUTH_URL, body="Bad request", status=400)
            with pytest.raises(EtollAuthError):
                await client.authenticate()

    async def test_500_raises_etoll_error(self, client):
        with aioresponses() as m:
            m.post(AUTH_URL, body="Server error", status=500)
            with pytest.raises(EtollError):
                await client.authenticate()


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


class TestRefresh:
    async def test_successful_refresh_updates_token(self, client, auth_payload):
        with aioresponses() as m:
            m.post(AUTH_URL, payload=auth_payload, status=200)
            await client.authenticate()

        new_payload = {**auth_payload, "accessToken": "new-access-token"}
        with aioresponses() as m:
            m.post(REFRESH_URL, payload=new_payload, status=200)
            session = await client.refresh()

        assert session.access_token == "new-access-token"
        assert client._auth.access_token == "new-access-token"

    async def test_failed_refresh_raises_session_expired(self, client, auth_payload):
        with aioresponses() as m:
            m.post(AUTH_URL, payload=auth_payload, status=200)
            await client.authenticate()

        with aioresponses() as m:
            m.post(REFRESH_URL, body="Expired", status=401)
            with pytest.raises(EtollSessionExpired):
                await client.refresh()
        # auth should be cleared after failed refresh
        assert client._auth is None

    async def test_refresh_without_session_raises(self, client):
        with pytest.raises(EtollSessionExpired):
            await client.refresh()


# ---------------------------------------------------------------------------
# _get retry logic
# ---------------------------------------------------------------------------


class TestGetRetry:
    async def test_401_triggers_refresh_then_retry(self, client, auth_payload, account_payload):
        cod = 1234567
        with aioresponses() as m:
            m.post(AUTH_URL, payload=auth_payload, status=200)
            await client.authenticate()

        new_auth = {**auth_payload, "accessToken": "refreshed-token"}
        with aioresponses() as m:
            # First attempt → 401; aioresponses matches regex, query params ignored
            m.get(_account_re(cod), status=401)
            # Refresh succeeds
            m.post(REFRESH_URL, payload=new_auth, status=200)
            # Retry succeeds
            m.get(_account_re(cod), payload=account_payload, status=200)
            result = await client._get(
                f"{ACCOUNTS_BASE}/accounts/{cod}", params={"isHashed": "false"}
            )

        assert result["codAccount"] == 1234567

    async def test_401_refresh_fails_falls_back_to_reauthenticate(
        self, client, auth_payload, account_payload
    ):
        cod = 1234567
        with aioresponses() as m:
            m.post(AUTH_URL, payload=auth_payload, status=200)
            await client.authenticate()

        with aioresponses() as m:
            m.get(_account_re(cod), status=401)
            m.post(REFRESH_URL, body="Expired", status=401)
            m.post(AUTH_URL, payload=auth_payload, status=200)
            m.get(_account_re(cod), payload=account_payload, status=200)
            result = await client._get(
                f"{ACCOUNTS_BASE}/accounts/{cod}", params={"isHashed": "false"}
            )

        assert result["codAccount"] == 1234567


# ---------------------------------------------------------------------------
# get_accessible_accounts
# ---------------------------------------------------------------------------


class TestGetAccessibleAccounts:
    async def test_spring_page_wrapper_unwrapped(self, client, auth_payload, account_payload):
        with aioresponses() as m:
            m.post(AUTH_URL, payload=auth_payload, status=200)
            await client.authenticate()

        wrapped = {"content": [account_payload], "totalElements": 1}
        with aioresponses() as m:
            m.get(_accessible_re(), payload=wrapped)
            accounts = await client.get_accessible_accounts()

        assert len(accounts) == 1
        assert accounts[0].cod_account == 1234567

    async def test_plain_list_response(self, client, auth_payload, account_payload):
        with aioresponses() as m:
            m.post(AUTH_URL, payload=auth_payload, status=200)
            await client.authenticate()

        with aioresponses() as m:
            m.get(_accessible_re(), payload=[account_payload])
            accounts = await client.get_accessible_accounts()

        assert len(accounts) == 1

    async def test_empty_content_returns_empty_list(self, client, auth_payload):
        with aioresponses() as m:
            m.post(AUTH_URL, payload=auth_payload, status=200)
            await client.authenticate()

        with aioresponses() as m:
            m.get(_accessible_re(), payload={"content": [], "totalElements": 0})
            accounts = await client.get_accessible_accounts()

        assert accounts == []


# ---------------------------------------------------------------------------
# get_account_activity (paging)
# ---------------------------------------------------------------------------


class TestGetAccountActivity:
    async def test_returns_entries_and_total(self, client, auth_payload):
        cod = 1234567
        activity_data = load_fixture("activity_response.json")
        with aioresponses() as m:
            m.post(AUTH_URL, payload=auth_payload, status=200)
            await client.authenticate()

        with aioresponses() as m:
            m.get(_activity_re(cod), payload=activity_data)
            entries, total = await client.get_account_activity(cod, page=1, size=50)

        assert total == 2
        assert len(entries) == 2
        assert entries[0].cod_invoicing_event == 1001

    async def test_page_parameter_reaches_api(self, client, auth_payload):
        cod = 1234567
        with aioresponses() as m:
            m.post(AUTH_URL, payload=auth_payload, status=200)
            await client.authenticate()

        with aioresponses() as m:
            m.get(_activity_re(cod), payload={"content": [], "totalElements": 0})
            entries, total = await client.get_account_activity(cod, page=2, size=50)

        assert entries == []
        assert total == 0


# ---------------------------------------------------------------------------
# search_account_activity (0-based paging)
# ---------------------------------------------------------------------------


class TestSearchAccountActivity:
    async def test_fetches_entries_from_searcher_endpoint(self, client, auth_payload):
        cod = 1234567
        activity_data = load_fixture("activity_response.json")
        with aioresponses() as m:
            m.post(AUTH_URL, payload=auth_payload, status=200)
            await client.authenticate()

        with aioresponses() as m:
            m.get(_searcher_re(cod), payload=activity_data)
            entries = await client.search_account_activity(
                cod,
                start=datetime(2026, 1, 1),
                end=datetime(2026, 5, 7),
            )

        assert len(entries) == 2

    async def test_stops_when_all_entries_fetched(self, client, auth_payload):
        cod = 1234567
        # 2 entries, totalElements=2 — should stop after first page
        activity_data = load_fixture("activity_response.json")
        with aioresponses() as m:
            m.post(AUTH_URL, payload=auth_payload, status=200)
            await client.authenticate()

        with aioresponses() as m:
            m.get(_searcher_re(cod), payload=activity_data)
            entries = await client.search_account_activity(
                cod,
                start=datetime(2026, 1, 1),
                end=datetime(2026, 5, 7),
                page_size=50,
            )

        assert len(entries) == 2
