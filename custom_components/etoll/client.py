"""Async client for the NSW E-Toll customer portal API.

This module is intentionally free of any Home Assistant imports so it can be
unit tested and run as a plain Python script. The Home Assistant integration
wraps it via a DataUpdateCoordinator.

The endpoints were captured from the React SPA at
https://account.myetoll.transport.nsw.gov.au — see README.md for the full
reverse-engineering notes.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# --- API surface --------------------------------------------------------------

API_BASE = "https://api.account.myetoll.transport.nsw.gov.au"
AUTH_URL = f"{API_BASE}/bis-public-portal-api/v1/authentication"
REFRESH_URL = f"{API_BASE}/bis-login-api/v1/authentication/refresh-token"
ACCOUNTS_BASE = f"{API_BASE}/bis-accounts-api/v1"

# The portal sends this header on every call. The backend appears to reject
# requests without it.
CALLER_APP_ID = "BISpublic"

# Currency in API responses is stored as an integer scaled by 100,000.
# e.g. decBalance: 4250000 == AUD 42.50
AMOUNT_SCALE = 100_000

# Activity event types observed on the prepaid account dashboard:
#   indEventType == 0  → "Pre-Paid Tolling Event"  (toll charge / trip)
#   indEventType == 1  → "Merchant Fee"            (debit fee)
#   indEventType == 3  → "Pre-Paid Account Top-up" or "Pre-paid merchant fee
#                        payment" (account credit)
EVENT_TYPE_TOLL = 0
EVENT_TYPE_FEE = 1
EVENT_TYPE_PAYMENT = 3

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)


# --- Exceptions ---------------------------------------------------------------


class EtollError(Exception):
    """Base exception for the eToll client."""


class EtollAuthError(EtollError):
    """Authentication failed (bad credentials, locked account, captcha)."""


class EtollSessionExpired(EtollError):
    """The bearer token has expired and a refresh is required."""


# --- Data shapes --------------------------------------------------------------


@dataclass
class Session:
    """Auth payload returned by /authentication."""

    access_token: str
    refresh_token: str
    user_id: str
    app_id: str
    last_access: datetime

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> "Session":
        return cls(
            access_token=payload["accessToken"],
            refresh_token=payload["refreshToken"],
            user_id=str(payload.get("userId", "")),
            app_id=str(payload.get("appId", "")),
            last_access=_parse_iso(payload.get("lastAccess")),
        )


@dataclass
class AccountSummary:
    """Subset of the /accounts/{id} payload that we surface as sensors."""

    cod_account: int
    balance: float
    last_balance_update: datetime | None
    low_balance_threshold: float | None
    top_up_amount: float | None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> "AccountSummary":
        return cls(
            cod_account=int(payload["codAccount"]),
            balance=_scale(payload.get("decBalance")),
            last_balance_update=_parse_iso(payload.get("datLastBalanceUpdate")),
            low_balance_threshold=_scale(payload.get("decLowBalance")),
            top_up_amount=_scale(payload.get("decTopupAmount")),
            raw=payload,
        )


@dataclass
class ActivityEntry:
    """A single row from /account-activity.

    The amount is signed: trips & fees are negative (money out), payments are
    positive (money in). The portal's table renders a sign based on
    `indCreditEvent`, so we replicate that here.
    """

    cod_invoicing_event: int
    cod_account: int
    type_label: str        # "Pre-Paid Tolling Event", "Merchant Fee", ...
    event_type: int        # 0 = toll, 1 = fee, 3 = payment
    is_credit: bool
    occurred_at: datetime  # datOccurrence — when the toll/fee actually happened
    posted_at: datetime    # datEvent — when the account was debited/credited
    gross_amount: float    # absolute value, AUD
    signed_amount: float   # negative for debits, positive for credits
    new_balance: float | None
    concession: str | None     # "WCX", "E-Toll Business Operations Centre"
    concession_label: str | None  # "Lane Cove Tunnel (180)", "E-Toll"
    plaza_name: str | None     # txtNameInitialTollPlaza (e.g. "412")
    plaza_description: str | None  # txtDescInitialTollPlaza (e.g. "Lane Cove North - Lane Cove West")
    vehicle_class: str | None
    tag_serial: int | None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> "ActivityEntry":
        gross = _scale(payload.get("decGrossValue")) or 0.0
        is_credit = bool(payload.get("indCreditEvent"))
        signed = gross if is_credit else -gross
        return cls(
            cod_invoicing_event=int(payload["codInvoicingEvent"]),
            cod_account=int(payload["codAccount"]),
            type_label=str(payload.get("txtTypeActivity") or ""),
            event_type=int(payload.get("indEventType", -1)),
            is_credit=is_credit,
            occurred_at=_parse_iso(payload.get("datOccurrence")) or _parse_iso(payload.get("datEvent")),
            posted_at=_parse_iso(payload.get("datEvent")) or _parse_iso(payload.get("datOccurrence")),
            gross_amount=gross,
            signed_amount=signed,
            new_balance=_scale(payload.get("decNewAccountBalance")),
            concession=payload.get("txtConcession"),
            concession_label=payload.get("txtAbbrevConcession"),
            plaza_name=payload.get("txtNameInitialTollPlaza"),
            plaza_description=payload.get("txtDescInitialTollPlaza"),
            vehicle_class=payload.get("txtVehicleClass"),
            tag_serial=payload.get("numTagSerial"),
            raw=payload,
        )

    @property
    def is_toll(self) -> bool:
        return self.event_type == EVENT_TYPE_TOLL

    @property
    def is_fee(self) -> bool:
        return self.event_type == EVENT_TYPE_FEE

    @property
    def is_payment(self) -> bool:
        return self.event_type == EVENT_TYPE_PAYMENT


# --- Helpers ------------------------------------------------------------------


def _scale(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return round(int(raw) / AMOUNT_SCALE, 2)
    except (TypeError, ValueError):
        return None


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    # The API returns naive ISO strings ("2026-04-29T19:40:23"). NSW backend
    # appears to be in Sydney local time. We treat the timestamps as naive
    # local time and expose them as such; sensor.py does any tz conversion.
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        return datetime.fromisoformat(text)
    except ValueError:
        _LOGGER.debug("Could not parse timestamp %r", text)
        return None


# --- Client -------------------------------------------------------------------


class EtollClient:
    """Asynchronous client for the NSW E-Toll customer API.

    Designed to be used as an async context manager:

        async with EtollClient(email, password) as client:
            await client.authenticate()
            account = await client.get_default_account()
            activity = await client.get_account_activity(account.cod_account)
    """

    def __init__(
        self,
        email: str,
        password: str,
        *,
        session: aiohttp.ClientSession | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> None:
        self._email = email
        self._password = password
        self._external_session = session is not None
        self._session = session
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._auth: Session | None = None

    async def __aenter__(self) -> "EtollClient":
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session and not self._external_session:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("Use EtollClient as an async context manager or pass a ClientSession")
        return self._session

    # ---- auth ----

    async def authenticate(self) -> Session:
        """Log in and capture the bearer token."""
        body = {"emailLogin": self._email, "password": self._password}
        async with self.session.post(
            AUTH_URL,
            json=body,
            headers={"accept": "application/json", "caller-app-id": CALLER_APP_ID},
        ) as resp:
            if resp.status in (400, 401, 403):
                detail = await _safe_text(resp)
                raise EtollAuthError(f"Authentication rejected ({resp.status}): {detail}")
            if resp.status not in (200, 201):
                detail = await _safe_text(resp)
                raise EtollError(f"Unexpected auth status {resp.status}: {detail}")
            payload = await resp.json()
        self._auth = Session.from_response(payload)
        _LOGGER.debug("Authenticated as user %s", self._auth.user_id)
        return self._auth

    async def refresh(self) -> Session:
        """Refresh the bearer token using the refresh token."""
        if self._auth is None:
            raise EtollSessionExpired("No active session to refresh")
        async with self.session.post(
            REFRESH_URL,
            json={
                "accessToken": self._auth.access_token,
                "refreshToken": self._auth.refresh_token,
                "userId": self._auth.user_id,
                "appId": self._auth.app_id,
            },
            headers={
                "accept": "application/json",
                "caller-app-id": CALLER_APP_ID,
            },
        ) as resp:
            if resp.status not in (200, 201):
                # Refresh failed — caller should re-auth.
                self._auth = None
                raise EtollSessionExpired(f"Refresh failed: {resp.status}")
            payload = await resp.json()
        self._auth = Session.from_response(payload)
        return self._auth

    async def _ensure_session(self) -> Session:
        if self._auth is None:
            return await self.authenticate()
        return self._auth

    def _auth_headers(self) -> dict[str, str]:
        assert self._auth is not None
        return {
            "accept": "application/json",
            "authorization": f"Bearer {self._auth.access_token}",
            "caller-app-id": CALLER_APP_ID,
        }

    async def _get(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        await self._ensure_session()
        for attempt in range(2):
            async with self.session.get(url, params=params, headers=self._auth_headers()) as resp:
                if resp.status == 401 and attempt == 0:
                    # Try a refresh once, then retry the request.
                    try:
                        await self.refresh()
                    except EtollSessionExpired:
                        await self.authenticate()
                    continue
                if resp.status >= 400:
                    detail = await _safe_text(resp)
                    raise EtollError(f"GET {url} → {resp.status}: {detail}")
                return await resp.json()
        raise EtollError(f"GET {url} failed after retry")

    # ---- accounts ----

    async def get_accessible_accounts(self) -> list[AccountSummary]:
        """List every account the logged-in user can access."""
        payload = await self._get(f"{ACCOUNTS_BASE}/accounts/accessible-accounts")
        # Spring Page wrapper: {content: [...], totalElements, ...}
        items = payload.get("content", payload) if isinstance(payload, dict) else payload
        return [AccountSummary.from_response(item) for item in items or []]

    async def get_account(self, cod_account: int) -> AccountSummary:
        """Fetch full account detail (balance, last update, etc.)."""
        payload = await self._get(
            f"{ACCOUNTS_BASE}/accounts/{cod_account}",
            params={"isHashed": "false"},
        )
        return AccountSummary.from_response(payload)

    async def get_default_account(self) -> AccountSummary:
        """Convenience: return the first accessible account.

        The NSW E-Toll dashboard auto-selects the first account when a user has
        only one. Most personal customers fall into this bucket.
        """
        accounts = await self.get_accessible_accounts()
        if not accounts:
            raise EtollError("No accessible accounts for this user")
        return accounts[0]

    # ---- activity ----

    async def get_account_activity(
        self,
        cod_account: int,
        *,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[ActivityEntry], int]:
        """Fetch one page of activity rows.

        Returns (entries, total_elements). Page numbering is 1-based to match
        the portal.
        """
        payload = await self._get(
            f"{ACCOUNTS_BASE}/accounts/{cod_account}/account-activity",
            params={"page": page, "size": size},
        )
        content = payload.get("content", []) if isinstance(payload, dict) else []
        total = int(payload.get("totalElements", len(content)))
        entries = [ActivityEntry.from_response(item) for item in content]
        return entries, total

    async def get_recent_activity(
        self,
        cod_account: int,
        *,
        since: datetime | None = None,
        max_pages: int = 10,
        page_size: int = 50,
    ) -> list[ActivityEntry]:
        """Fetch activity rows up to `max_pages` deep, optionally filtered.

        If `since` is supplied, paging stops as soon as a row is older than
        `since` — handy for the integration's regular polling, where we only
        need new rows.
        """
        all_entries: list[ActivityEntry] = []
        for page in range(1, max_pages + 1):
            entries, total = await self.get_account_activity(
                cod_account, page=page, size=page_size
            )
            for entry in entries:
                if since is not None and entry.posted_at and entry.posted_at < since:
                    return all_entries
                all_entries.append(entry)
            if not entries or len(all_entries) >= total:
                break
        return all_entries


async def _safe_text(resp: aiohttp.ClientResponse) -> str:
    try:
        return (await resp.text())[:500]
    except Exception:  # pragma: no cover - defensive
        return "<no body>"


# --- Toll-relief helpers ------------------------------------------------------


def week_bounds(reference: datetime, *, week_starts_on: int = 0) -> tuple[datetime, datetime]:
    """Return [start, end) of the week containing `reference`.

    `week_starts_on`: 0 == Monday, 6 == Sunday. NSW Toll Relief uses
    Monday-Sunday weeks for the $60 cap so 0 is the right default.
    """
    ref = reference if reference.tzinfo is None else reference.astimezone()
    start_date = ref - timedelta(days=(ref.weekday() - week_starts_on) % 7)
    start = datetime.combine(start_date.date(), datetime.min.time())
    end = start + timedelta(days=7)
    return start, end


def year_bounds(reference: datetime) -> tuple[datetime, datetime]:
    start = datetime(reference.year, 1, 1)
    end = datetime(reference.year + 1, 1, 1)
    return start, end


def sum_tolls(entries: list[ActivityEntry], start: datetime, end: datetime) -> float:
    """Sum toll-event spend (absolute $) within [start, end)."""
    total = 0.0
    for e in entries:
        if not e.is_toll or e.posted_at is None:
            continue
        ts = e.posted_at if e.posted_at.tzinfo is None else e.posted_at.replace(tzinfo=None)
        if start <= ts < end:
            total += e.gross_amount
    return round(total, 2)


def latest_toll(entries: list[ActivityEntry]) -> ActivityEntry | None:
    """Return the most recent toll event (None if no trips in `entries`)."""
    candidates = [e for e in entries if e.is_toll and e.posted_at]
    if not candidates:
        return None
    return max(candidates, key=lambda e: e.posted_at)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


__all__ = [
    "ActivityEntry",
    "AccountSummary",
    "AMOUNT_SCALE",
    "CALLER_APP_ID",
    "EVENT_TYPE_FEE",
    "EVENT_TYPE_PAYMENT",
    "EVENT_TYPE_TOLL",
    "EtollAuthError",
    "EtollClient",
    "EtollError",
    "EtollSessionExpired",
    "Session",
    "latest_toll",
    "sum_tolls",
    "utc_now",
    "week_bounds",
    "year_bounds",
]
