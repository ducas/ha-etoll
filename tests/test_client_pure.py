"""Tests for pure (non-HTTP) functions in client.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.etoll.client import (
    ActivityEntry,
    _parse_iso,
    _scale,
    compute_yearly_rebate,
    latest_toll,
    sum_tolls,
    week_bounds,
    year_bounds,
)
from tests.conftest import make_payment_entry, make_toll_entry

# ---------------------------------------------------------------------------
# _scale
# ---------------------------------------------------------------------------


class TestScale:
    def test_none_returns_none(self):
        assert _scale(None) is None

    def test_integer_scaled(self):
        assert _scale(4_250_000) == 42.50

    def test_string_integer(self):
        assert _scale("630000") == 6.30

    def test_zero(self):
        assert _scale(0) == 0.0

    def test_non_numeric_returns_none(self):
        assert _scale("abc") is None

    def test_rounds_to_two_decimal_places(self):
        # 1 / 100_000 = 0.000_01 — rounds to 0.0
        assert _scale(1) == 0.0
        # 50_001 / 100_000 = 0.50001 — rounds to 0.50
        assert _scale(50_001) == 0.50


# ---------------------------------------------------------------------------
# _parse_iso
# ---------------------------------------------------------------------------


class TestParseIso:
    def test_naive_iso(self):
        dt = _parse_iso("2026-05-07T08:15:00")
        assert dt == datetime(2026, 5, 7, 8, 15, 0)
        assert dt.tzinfo is None

    def test_z_suffix_gives_utc(self):
        dt = _parse_iso("2026-05-07T08:15:00Z")
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0

    def test_none_returns_none(self):
        assert _parse_iso(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_iso("") is None

    def test_invalid_string_returns_none(self):
        assert _parse_iso("not-a-date") is None

    def test_datetime_passthrough(self):
        dt = datetime(2026, 5, 7, 8, 0, 0)
        assert _parse_iso(dt) is dt


# ---------------------------------------------------------------------------
# ActivityEntry.from_response
# ---------------------------------------------------------------------------


class TestActivityEntryFromResponse:
    def test_toll_debit(self):
        payload = {
            "codInvoicingEvent": 1001,
            "codAccount": 1234567,
            "txtTypeActivity": "Pre-Paid Tolling Event",
            "indEventType": 0,
            "indCreditEvent": False,
            "datOccurrence": "2026-05-07T08:10:00",
            "datEvent": "2026-05-07T08:15:00",
            "decGrossValue": 630_000,
            "decNewAccountBalance": 4_250_000,
            "numTagSerial": 98765,
        }
        entry = ActivityEntry.from_response(payload)
        assert entry.cod_invoicing_event == 1001
        assert entry.gross_amount == 6.30
        assert entry.signed_amount == -6.30
        assert entry.is_credit is False
        assert entry.is_toll is True
        assert entry.tag_serial == 98765

    def test_payment_credit(self):
        payload = {
            "codInvoicingEvent": 2001,
            "codAccount": 1234567,
            "txtTypeActivity": "Account Top-up",
            "indEventType": 3,
            "indCreditEvent": True,
            "datOccurrence": "2026-05-06T10:00:00",
            "datEvent": "2026-05-06T10:00:00",
            "decGrossValue": 5_000_000,
        }
        entry = ActivityEntry.from_response(payload)
        assert entry.gross_amount == 50.00
        assert entry.signed_amount == 50.00
        assert entry.is_credit is True
        assert entry.is_payment is True
        assert entry.tag_serial is None

    def test_missing_optional_fields_are_none(self):
        payload = {
            "codInvoicingEvent": 3001,
            "codAccount": 1234567,
            "datOccurrence": "2026-05-07T08:00:00",
            "datEvent": "2026-05-07T08:00:00",
            "decGrossValue": 0,
        }
        entry = ActivityEntry.from_response(payload)
        assert entry.concession is None
        assert entry.concession_label is None
        assert entry.plaza_name is None
        assert entry.plaza_description is None
        assert entry.vehicle_class is None
        assert entry.tag_serial is None
        assert entry.new_balance is None


# ---------------------------------------------------------------------------
# week_bounds
# ---------------------------------------------------------------------------


class TestWeekBounds:
    def test_monday_is_start_of_its_own_week(self):
        monday = datetime(2026, 5, 4)  # Monday 4 May 2026
        start, end = week_bounds(monday)
        assert start == datetime(2026, 5, 4)
        assert end == datetime(2026, 5, 11)

    def test_wednesday_maps_to_preceding_monday(self):
        wednesday = datetime(2026, 5, 6)
        start, end = week_bounds(wednesday)
        assert start == datetime(2026, 5, 4)
        assert end == datetime(2026, 5, 11)

    def test_sunday_maps_to_preceding_monday(self):
        sunday = datetime(2026, 5, 10)
        start, end = week_bounds(sunday)
        assert start == datetime(2026, 5, 4)
        assert end == datetime(2026, 5, 11)

    def test_tz_aware_input_is_handled(self):
        aware = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
        start, end = week_bounds(aware)
        assert start.tzinfo is None  # result is always naive

    def test_custom_week_starts_on_sunday(self):
        # week_starts_on=6 → Sunday-first weeks
        sunday = datetime(2026, 5, 10)
        start, end = week_bounds(sunday, week_starts_on=6)
        assert start == datetime(2026, 5, 10)
        assert end == datetime(2026, 5, 17)

        monday = datetime(2026, 5, 4)
        start, end = week_bounds(monday, week_starts_on=6)
        assert start == datetime(2026, 5, 3)
        assert end == datetime(2026, 5, 10)


# ---------------------------------------------------------------------------
# year_bounds
# ---------------------------------------------------------------------------


class TestYearBounds:
    def test_mid_year(self):
        start, end = year_bounds(datetime(2026, 5, 7))
        assert start == datetime(2026, 1, 1)
        assert end == datetime(2027, 1, 1)

    def test_jan_1(self):
        start, end = year_bounds(datetime(2026, 1, 1))
        assert start == datetime(2026, 1, 1)

    def test_dec_31(self):
        start, end = year_bounds(datetime(2026, 12, 31))
        assert start == datetime(2026, 1, 1)
        assert end == datetime(2027, 1, 1)


# ---------------------------------------------------------------------------
# sum_tolls
# ---------------------------------------------------------------------------


class TestSumTolls:
    def _monday_week(self):
        start = datetime(2026, 5, 4)  # Monday
        end = datetime(2026, 5, 11)  # next Monday
        return start, end

    def test_empty_list(self):
        start, end = self._monday_week()
        assert sum_tolls([], start, end) == 0.0

    def test_single_toll_in_range(self):
        start, end = self._monday_week()
        entries = [make_toll_entry(1, 123, 6.30, datetime(2026, 5, 6, 8, 0))]
        assert sum_tolls(entries, start, end) == 6.30

    def test_toll_at_start_is_included(self):
        start, end = self._monday_week()
        entries = [make_toll_entry(1, 123, 5.00, start)]
        assert sum_tolls(entries, start, end) == 5.00

    def test_toll_at_end_is_excluded(self):
        start, end = self._monday_week()
        entries = [make_toll_entry(1, 123, 5.00, end)]
        assert sum_tolls(entries, start, end) == 0.0

    def test_payment_excluded(self):
        start, end = self._monday_week()
        entries = [
            make_toll_entry(1, 123, 6.30, datetime(2026, 5, 6)),
            make_payment_entry(2, 123, 50.00, datetime(2026, 5, 6)),
        ]
        assert sum_tolls(entries, start, end) == 6.30

    def test_toll_outside_range_excluded(self):
        start, end = self._monday_week()
        entries = [make_toll_entry(1, 123, 10.00, datetime(2026, 4, 30))]
        assert sum_tolls(entries, start, end) == 0.0

    def test_none_posted_at_skipped(self):
        start, end = self._monday_week()
        entry = make_toll_entry(1, 123, 5.00, datetime(2026, 5, 6))
        entry = ActivityEntry(**{**entry.__dict__, "posted_at": None, "occurred_at": None})
        assert sum_tolls([entry], start, end) == 0.0

    def test_rounds_to_two_decimal_places(self):
        start, end = self._monday_week()
        # Three entries of $1/3 = 0.333... each — floating point is tricky
        entries = [
            make_toll_entry(i, 123, round(1 / 3, 5), datetime(2026, 5, 5)) for i in range(1, 4)
        ]
        result = sum_tolls(entries, start, end)
        assert isinstance(result, float)
        # Result should be rounded to 2dp
        assert result == round(result, 2)

    def test_multiple_tolls_summed(self):
        start, end = self._monday_week()
        entries = [
            make_toll_entry(1, 123, 6.30, datetime(2026, 5, 4)),
            make_toll_entry(2, 123, 4.20, datetime(2026, 5, 5)),
            make_toll_entry(3, 123, 7.50, datetime(2026, 5, 7)),
        ]
        assert sum_tolls(entries, start, end) == 18.00


# ---------------------------------------------------------------------------
# compute_yearly_rebate
# ---------------------------------------------------------------------------


class TestComputeYearlyRebate:
    def _year(self):
        return datetime(2026, 1, 1), datetime(2027, 1, 1)

    def test_empty_returns_zero(self):
        year_start, year_end = self._year()
        assert compute_yearly_rebate([], year_start, year_end) == 0.0

    def test_below_threshold_returns_zero(self):
        year_start, year_end = self._year()
        entries = [make_toll_entry(1, 123, 30.00, datetime(2026, 5, 6))]
        assert compute_yearly_rebate(entries, year_start, year_end) == 0.0

    def test_exactly_at_threshold_returns_zero(self):
        year_start, year_end = self._year()
        entries = [make_toll_entry(1, 123, 60.00, datetime(2026, 5, 6))]
        assert compute_yearly_rebate(entries, year_start, year_end) == 0.0

    def test_spend_above_threshold(self):
        year_start, year_end = self._year()
        # $70 this week → $10 rebate
        entries = [make_toll_entry(1, 123, 70.00, datetime(2026, 5, 6))]
        assert compute_yearly_rebate(entries, year_start, year_end) == 10.00

    def test_spend_above_upper_cap_clamped(self):
        year_start, year_end = self._year()
        # $500 this week — upper cap is $400, so claimable = 400 - 60 = $340
        entries = [make_toll_entry(1, 123, 500.00, datetime(2026, 5, 6))]
        assert compute_yearly_rebate(entries, year_start, year_end) == 340.00

    def test_multiple_weeks_summed(self):
        year_start, year_end = self._year()
        # Week 1: $70 → $10 rebate
        # Week 2: $80 → $20 rebate
        entries = [
            make_toll_entry(1, 123, 70.00, datetime(2026, 5, 6)),  # week of Mon 4 May
            make_toll_entry(2, 123, 80.00, datetime(2026, 5, 13)),  # week of Mon 11 May
        ]
        assert compute_yearly_rebate(entries, year_start, year_end) == 30.00

    def test_yearly_cap_applied(self):
        year_start, year_end = self._year()
        # 20 weeks of $340 rebate each = $6800 > $5000 cap
        entries = [
            make_toll_entry(
                i,
                123,
                400.00,
                datetime(2026, 1, 5) + timedelta(weeks=i),
            )
            for i in range(20)
        ]
        result = compute_yearly_rebate(entries, year_start, year_end)
        assert result == 5000.00

    def test_entries_outside_year_excluded(self):
        year_start, year_end = self._year()  # 2026
        entries = [
            make_toll_entry(1, 123, 100.00, datetime(2025, 12, 31)),  # prior year
        ]
        assert compute_yearly_rebate(entries, year_start, year_end) == 0.0

    def test_payments_excluded(self):
        year_start, year_end = self._year()
        entries = [
            make_toll_entry(1, 123, 70.00, datetime(2026, 5, 6)),
            make_payment_entry(2, 123, 500.00, datetime(2026, 5, 6)),
        ]
        # Only the $70 toll counts
        assert compute_yearly_rebate(entries, year_start, year_end) == 10.00

    def test_custom_thresholds(self):
        year_start, year_end = self._year()
        entries = [make_toll_entry(1, 123, 60.00, datetime(2026, 5, 6))]
        result = compute_yearly_rebate(
            entries,
            year_start,
            year_end,
            weekly_threshold=50.0,
            weekly_upper_cap=200.0,
            yearly_rebate_cap=2000.0,
        )
        assert result == 10.00  # 60 - 50


# ---------------------------------------------------------------------------
# latest_toll
# ---------------------------------------------------------------------------


class TestLatestToll:
    def test_empty_list_returns_none(self):
        assert latest_toll([]) is None

    def test_no_toll_entries_returns_none(self):
        entries = [make_payment_entry(1, 123, 50.00, datetime(2026, 5, 6))]
        assert latest_toll(entries) is None

    def test_returns_most_recent(self):
        entries = [
            make_toll_entry(1, 123, 5.00, datetime(2026, 5, 5)),
            make_toll_entry(2, 123, 6.30, datetime(2026, 5, 7)),
            make_toll_entry(3, 123, 4.00, datetime(2026, 5, 6)),
        ]
        result = latest_toll(entries)
        assert result is not None
        assert result.cod_invoicing_event == 2

    def test_unsorted_input(self):
        entries = [
            make_toll_entry(3, 123, 4.00, datetime(2026, 5, 6)),
            make_toll_entry(1, 123, 5.00, datetime(2026, 5, 5)),
            make_toll_entry(2, 123, 6.30, datetime(2026, 5, 7)),
        ]
        result = latest_toll(entries)
        assert result is not None
        assert result.cod_invoicing_event == 2

    def test_ignores_entries_with_none_posted_at(self):
        early = make_toll_entry(1, 123, 5.00, datetime(2026, 5, 5))
        late_no_ts = make_toll_entry(2, 123, 6.30, datetime(2026, 5, 7))
        late_no_ts = ActivityEntry(
            **{**late_no_ts.__dict__, "posted_at": None, "occurred_at": None}
        )
        entries = [early, late_no_ts]
        result = latest_toll(entries)
        assert result is not None
        assert result.cod_invoicing_event == 1
