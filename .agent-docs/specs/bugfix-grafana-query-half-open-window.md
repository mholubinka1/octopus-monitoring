# Fix double-counted cost in Grafana queries (inclusive-both-ends join)

## Problem Statement

Every query in `grafana/mariadb/queries.md` that joins `consumption` to `product_rate` and/or `agreement` uses `c.period_from BETWEEN valid_from AND COALESCE(valid_to, '9999-12-31 23:59:59')`. `BETWEEN` is inclusive on both ends. Because `consumption.period_from` is recorded on the exact same half-hourly grid as `product_rate`'s (and `agreement`'s) `valid_from`/`valid_to` windows, a consumption timestamp that lands exactly on a boundary — which is nearly every row, since adjacent rate windows are back-to-back (one row's `valid_to` equals the next row's `valid_from`) — matches **two** rate rows instead of one. `SUM(c.est_kwh * pr.unit_rate)` then counts that half-hour's cost twice.

Confirmed live against the real production database: the Yesterday's Cost panel showed £6.01 against a true £3.25 (agreed by both the app's own numbers and Octopus Compare). Diagnostics traced it to the join producing 96 rows instead of the correct 48 for a 48-half-hour day — a clean 2x fan-out — and a row-level query showed `period_from = 2026-07-26 01:00:00` matching both the `product_rate` row ending at `01:00:00` and the row starting at `01:00:00`.

## Solution

Replace the inclusive-both-ends `BETWEEN` pattern with a half-open window everywhere it's used to join `consumption` to `product_rate` or `agreement`: `c.period_from >= valid_from AND c.period_from < COALESCE(valid_to, '9999-12-31 23:59:59')`. This attributes a boundary timestamp to the window that *starts* there, not also to the window that ends there, while keeping the file's existing `COALESCE`-to-a-sentinel-date idiom for "open-ended means unbounded" rather than introducing a new pattern.

## User Stories

1. As the account holder, I want the Grafana cost panels to show my actual spend, so that I can trust the dashboard instead of a number that's silently ~2x too high.
2. As a future reader of `grafana/mariadb/queries.md`, I want every query in the file to use the same correct join pattern, so that copying any panel's query doesn't reintroduce this bug in a new panel.

## Implementation Decisions

- **File**: `grafana/mariadb/queries.md` only — this is a SQL reference document meant to be pasted into Grafana's query editor, not executable application code. No `app/` or `tests/` changes.
- Fix the join condition in every query that currently uses the inclusive `BETWEEN` pattern against `product_rate.valid_from`/`valid_to` or `agreement.valid_from`/`valid_to`:
  - **Yesterday's Cost** (Row 1 — Cost Summary)
  - **Half-hourly Cost** (Row 2 — Electricity)
  - **p/kWh Efficiency vs Day's Avg Rate** (Row 2 — Electricity)
  - **Daily Average Cost — 7-Day Rolling Average, 12 Weeks** (Row 2 — Electricity)
  - **Standing Charge vs Unit-Rate Cost Split** (Row 2 — Electricity)
  - **Gas Cost** (Row 3 — Gas)
- Each of the above has two occurrences of the pattern per query — one for the `agreement` join, one for the `product_rate` join — both get the same half-open correction.
- Queries that don't join `consumption` to `product_rate`/`agreement` at all are unaffected and untouched: This Billing Period's Cost So Far, Total Expected Cost, Current Billing Period, Price Curve, Half-hourly Consumption, Cheapest N-Hour Window, Day-of-Week Average Consumption, Daily Average Usage, Consumption Heatmap, Gas Consumption, the Monthly/Weekly-YoY panels (read from `daily_consumption_summary`, no join), and the Health row.
- Add a short standing note near the top of the file (next to the existing "Schema assumed" section) documenting the half-open convention, so future panels added to this file don't reintroduce the inclusive-both-ends bug.

## Testing Decisions

- No automated test — this is a documentation file with no test harness (SQL meant for Grafana's query editor, not exercised by the app's test suite).
- Acceptance check: after the fix, re-run the corrected Yesterday's Cost query directly against the production database (via Grafana Explore) and confirm it returns £3.25, matching the app's own cost display and Octopus Compare's independent figure for the same day.

## Out of Scope

- Any change to application code (`app/`) — the underlying `consumption`/`product_rate`/`agreement` data and the app's own cost calculations (`app/data/cost_forecast.py`, `app/data/mysql/client.py`) are unaffected; this bug exists only in the standalone Grafana reference queries, not in the app's own cost-forecast pipeline.
- Building the actual Grafana dashboard (`feature-grafana-dashboard.md`'s JSON-provisioning scope) — this fix only corrects the SQL in `queries.md`; the user is currently building dashboard panels manually in the Grafana UI, one at a time, outside of this repo change.

## Further Notes

Found and diagnosed live while manually walking through building Grafana panels from this file's queries, cross-referencing the resulting panel value against the app's own displayed cost and Octopus Compare.
