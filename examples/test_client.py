"""Standalone smoke test for the eToll client.

Run from the project root with your credentials in env vars so we don't bake
them into the file:

    ETOLL_EMAIL='you@example.com' ETOLL_PASSWORD='...' \
        python examples/test_client.py

The script prints account balance plus week/year toll totals, mirroring what
the HA integration will surface as sensors. Useful for verifying the API
contract before installing the integration on a live HA instance.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# Allow running without installing — add the custom_components dir to the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))

from etoll.client import (  # noqa: E402  (import after sys.path tweak)
    EtollClient,
    compute_yearly_rebate,
    latest_toll,
    sum_tolls,
    week_bounds,
    year_bounds,
)


async def main() -> int:
    email = os.environ.get("ETOLL_EMAIL")
    password = os.environ.get("ETOLL_PASSWORD")
    if not email or not password:
        print("Set ETOLL_EMAIL and ETOLL_PASSWORD env vars.", file=sys.stderr)
        return 2

    async with EtollClient(email=email, password=password) as client:
        await client.authenticate()
        account = await client.get_default_account()
        full = await client.get_account(account.cod_account)

        print(f"Account:      {full.cod_account}")
        print(f"Balance:      ${full.balance:.2f}")
        print(f"Last update:  {full.last_balance_update}")
        if full.low_balance_threshold:
            print(f"Low balance:  ${full.low_balance_threshold:.2f}")
        if full.top_up_amount:
            print(f"Top-up size:  ${full.top_up_amount:.2f}")

        now = datetime.now()
        wstart, wend = week_bounds(now)
        ystart, yend = year_bounds(now)

        # Use the searcher endpoint for accurate YTD figures — the regular
        # account-activity endpoint is limited to the current quarter only.
        print("Fetching YTD activity via searcher endpoint...")
        activity = await client.search_account_activity(
            account.cod_account,
            start=ystart,
            end=now,
            page_size=50,
            max_pages=40,
        )

        print(f"Activity rows fetched (YTD): {len(activity)}")
        weekly_spend = sum_tolls(activity, wstart, wend)
        weekly_excess = max(0.0, weekly_spend - 60.0)
        weekly_claimable = min(weekly_excess, 340.0)
        yearly_rebate = compute_yearly_rebate(activity, ystart, yend)

        print(f"Tolls this week  ({wstart:%Y-%m-%d} → {wend:%Y-%m-%d}): ${weekly_spend:.2f}")
        print(f"  Excess over $60 cap:     ${weekly_excess:.2f}")
        print(f"  Claimable this week:     ${weekly_claimable:.2f}  (capped at $340)")
        print(f"Tolls this year  ({ystart:%Y-%m-%d} → {yend:%Y-%m-%d}): "
              f"${sum_tolls(activity, ystart, yend):.2f}")
        print(f"  Yearly rebate accrued:   ${yearly_rebate:.2f}  (cap $5,000)")
        print(f"  Yearly rebate remaining: ${max(0.0, 5000.0 - yearly_rebate):.2f}")

        last = latest_toll(activity)
        if last:
            print()
            print("Most recent trip:")
            print(f"  When:    {last.posted_at}")
            print(f"  Amount:  ${last.gross_amount:.2f}")
            print(f"  Where:   {last.plaza_description or last.plaza_name}")
            print(f"  Carrier: {last.concession_label or last.concession}")

        # Per-tag breakdown
        tag_serials = sorted({
            e.tag_serial for e in activity
            if e.is_toll and e.tag_serial is not None
        })
        print()
        print(f"Discovered {len(tag_serials)} tag serial(s): {tag_serials}")
        for serial in tag_serials:
            tag_activity = [e for e in activity if e.tag_serial == serial]
            tag_weekly = sum_tolls(tag_activity, wstart, wend)
            tag_yearly = sum_tolls(tag_activity, ystart, yend)
            tag_rebate = compute_yearly_rebate(tag_activity, ystart, yend)
            tag_last = latest_toll(tag_activity)
            print()
            print(f"  Tag {serial}:")
            print(f"    Tolls this week:         ${tag_weekly:.2f}")
            print(f"    Claimable this week:     ${min(max(0.0, tag_weekly - 60.0), 340.0):.2f}")
            print(f"    Tolls this year:         ${tag_yearly:.2f}")
            print(f"    Yearly rebate accrued:   ${tag_rebate:.2f}")
            print(f"    Yearly rebate remaining: ${max(0.0, 5000.0 - tag_rebate):.2f}")
            if tag_last:
                print(f"    Last trip: {tag_last.posted_at}  ${tag_last.gross_amount:.2f}"
                      f"  {tag_last.plaza_description or tag_last.plaza_name}")

        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
