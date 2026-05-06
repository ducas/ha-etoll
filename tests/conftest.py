"""Shared fixtures for ha-etoll tests."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.etoll.client import (
    EVENT_TYPE_PAYMENT,
    EVENT_TYPE_TOLL,
    AccountSummary,
    ActivityEntry,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Raw fixture data
# ---------------------------------------------------------------------------


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest.fixture
def auth_payload() -> dict[str, Any]:
    return load_fixture("auth_response.json")


@pytest.fixture
def account_payload() -> dict[str, Any]:
    return load_fixture("account_response.json")


@pytest.fixture
def activity_payload() -> dict[str, Any]:
    return load_fixture("activity_response.json")


# ---------------------------------------------------------------------------
# Domain-object factories
# ---------------------------------------------------------------------------


def make_toll_entry(
    cod: int,
    cod_account: int,
    gross_amount: float,
    posted_at: datetime,
    *,
    tag_serial: int | None = None,
    occurred_at: datetime | None = None,
) -> ActivityEntry:
    """Create a toll ActivityEntry with the given parameters."""
    scaled = int(gross_amount * 100_000)
    return ActivityEntry(
        cod_invoicing_event=cod,
        cod_account=cod_account,
        type_label="Pre-Paid Tolling Event",
        event_type=EVENT_TYPE_TOLL,
        is_credit=False,
        occurred_at=occurred_at or posted_at,
        posted_at=posted_at,
        gross_amount=gross_amount,
        signed_amount=-gross_amount,
        new_balance=None,
        concession=None,
        concession_label=None,
        plaza_name=None,
        plaza_description=None,
        vehicle_class=None,
        tag_serial=tag_serial,
        raw={"codInvoicingEvent": cod, "decGrossValue": scaled},
    )


def make_payment_entry(
    cod: int,
    cod_account: int,
    gross_amount: float,
    posted_at: datetime,
) -> ActivityEntry:
    """Create a payment (credit) ActivityEntry."""
    scaled = int(gross_amount * 100_000)
    return ActivityEntry(
        cod_invoicing_event=cod,
        cod_account=cod_account,
        type_label="Pre-Paid Account Top-up",
        event_type=EVENT_TYPE_PAYMENT,
        is_credit=True,
        occurred_at=posted_at,
        posted_at=posted_at,
        gross_amount=gross_amount,
        signed_amount=gross_amount,
        new_balance=None,
        concession=None,
        concession_label=None,
        plaza_name=None,
        plaza_description=None,
        vehicle_class=None,
        tag_serial=None,
        raw={"codInvoicingEvent": cod, "decGrossValue": scaled},
    )


def make_account(
    cod_account: int = 1234567,
    balance: float = 42.50,
) -> AccountSummary:
    return AccountSummary(
        cod_account=cod_account,
        balance=balance,
        last_balance_update=datetime(2026, 5, 7, 8, 0, 0),
        low_balance_threshold=10.0,
        top_up_amount=50.0,
        raw={},
    )


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> MagicMock:
    """EtollClient mock with common methods pre-wired as AsyncMocks."""
    client = MagicMock()
    client.authenticate = AsyncMock(return_value=None)
    client.get_account = AsyncMock(return_value=make_account())
    client.get_default_account = AsyncMock(return_value=make_account())
    client.get_accessible_accounts = AsyncMock(return_value=[make_account()])
    client.get_account_activity = AsyncMock(return_value=([], 0))
    client.get_recent_activity = AsyncMock(return_value=[])
    client.search_account_activity = AsyncMock(return_value=[])
    client.close = AsyncMock(return_value=None)
    return client
