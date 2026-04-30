# NSW E-Toll for Home Assistant

A Home Assistant custom integration that logs into your **NSW E-Toll** account
(myetoll.transport.nsw.gov.au) and exposes balance and trip activity as
sensors. Built primarily so you can tell, at a glance, whether you're on
track to qualify for the NSW Toll Relief weekly rebate.

## What it tracks

| Entity | Description |
| --- | --- |
| `sensor.etoll_<id>_account_balance` | Current account balance (AUD) |
| `sensor.etoll_<id>_toll_spend_this_week` | Sum of toll-event amounts since Monday 00:00 |
| `sensor.etoll_<id>_weekly_cap_excess` | `max(0, weekly_spend - cap)` — the amount above the configured weekly cap (default $60) |
| `sensor.etoll_<id>_toll_spend_this_year` | Year-to-date toll spend |
| `sensor.etoll_<id>_trips_this_week` | Count of trip events in the current week |
| `sensor.etoll_<id>_trips_this_year` | Count of trip events year-to-date |
| `sensor.etoll_<id>_last_trip_amount` | Amount of the most recent toll event |
| `sensor.etoll_<id>_last_trip_at` | Timestamp of the most recent toll event |
| `sensor.etoll_<id>_last_balance_update` | When the eToll backend last refreshed your balance (diagnostic) |
| `binary_sensor.etoll_<id>_rebate_eligible_this_week` | `on` if `weekly_spend > weekly_cap` |

The `last_trip_amount` sensor's attributes include the concession (`Lane Cove
Tunnel`, `E-Toll`, etc.), the plaza description (`Lane Cove North - Lane Cove
West`), the vehicle class, and the tag serial.

## How it works

The integration calls the same backend API that the React-based myetoll
portal uses:

- `POST /bis-public-portal-api/v1/authentication` — sign in, returns a JWT
  access token + refresh token. **No reCAPTCHA required** for normal logins.
- `GET /bis-accounts-api/v1/accounts/{accountId}` — account snapshot
  (balance, low-balance threshold, top-up amount, last balance update).
- `GET /bis-accounts-api/v1/accounts/{accountId}/account-activity?page=N&size=N`
  — paged activity feed (trips, fees, payments). Currency values are stored
  scaled by 100,000 in the JSON; the client divides automatically.

The `caller-app-id: BISpublic` header is required on every request.

The integration:

- Stores the access token in memory only (HA's encrypted config holds your
  credentials).
- Refreshes the access token via the refresh-token endpoint when a request
  hits 401, and re-authenticates if that fails.
- Caches activity rows by `codInvoicingEvent` so subsequent polls only need
  to fetch new entries.
- On first start, paginates up to 1,000 rows back to seed year-to-date
  totals; thereafter polls only enough pages to find new entries.

## Installation

### HACS (recommended)

1. In HACS, open **Integrations → ⋮ → Custom repositories**.
2. Add this repository's URL with category **Integration**.
3. Install **NSW E-Toll**, then restart Home Assistant.
4. **Settings → Devices & Services → Add Integration → NSW E-Toll** and enter
   your credentials.

### Manual

Copy the `custom_components/etoll/` directory into your
`<config>/custom_components/` folder, restart, then add via Devices &
Services as above.

## Configuration

| Field | Default | Notes |
| --- | --- | --- |
| Email or account number | — | Same login you use on the portal |
| Password | — | Stored in HA's encrypted config |
| Refresh interval (minutes) | 60 | Minimum 15 minutes |
| Weekly toll cap (AUD) | 60.0 | NSW Toll Relief threshold; change if the scheme changes |

After install, the **Configure** button on the integration card lets you
adjust the refresh interval and weekly cap without re-entering credentials.

## NSW Toll Relief context

At time of writing, NSW Toll Relief reimburses toll spend above $60 per week
(Mon–Sun). The `weekly_cap_excess` sensor shows that excess directly so you
can decide whether to keep driving toll roads or take side streets for the
rest of the week. Always cross-check the actual scheme rules at
[nsw.gov.au/toll-relief](https://www.nsw.gov.au/transport/roads/toll-relief)
— the sensor reflects raw spend, not the rebate amount, and Transport for
NSW periodically tweaks the eligibility rules.

## Smoke testing

Before installing the integration, you can verify the client works against
your account from a regular Python environment:

```bash
ETOLL_EMAIL='you@example.com' ETOLL_PASSWORD='…' \
    python examples/test_client.py
```

Sample output (values are illustrative only):

```
Account:      1234567
Balance:      $42.50
Last update:  2025-09-15 21:14:08
Activity rows fetched: 47
Tolls this week  (2025-09-15 → 2025-09-22): $24.30
Tolls this year  (2025-01-01 → 2026-01-01): $312.45
Most recent trip:
  When:    2025-09-15 17:42:11
  Amount:  $9.27
  Where:   Lane Cove North - Lane Cove West
  Carrier: Lane Cove Tunnel (180)
```

## Caveats

- Only **prepaid (tag-based) accounts** have been verified. Postpaid accounts
  will likely work — same API, different `decBalance` semantics — but
  haven't been smoke-tested. File an issue with a HAR if yours misbehaves.
- The portal occasionally surfaces a reCAPTCHA challenge after suspicious
  activity. The integration does not handle that case automatically; you'll
  need to log in manually once via the website and the API will go back to
  password-only auth.
- All timestamps from the backend are naive ISO strings in Sydney local
  time. The integration converts them via the host's local timezone — make
  sure HA is configured for `Australia/Sydney` for accurate week boundaries.

## License

MIT — see [LICENSE](LICENSE).
