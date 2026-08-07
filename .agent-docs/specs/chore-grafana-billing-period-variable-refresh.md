# Billing Period Progress Panel: Keep Title in Sync With Auto-Refresh

## Problem Statement

The "Billing Period Progress" Grafana panel's title interpolates two dashboard
variables, `$billing_period_start` and `$billing_period_end`, each populated by a query
against `cost_forecast` (`ORDER BY computed_at DESC LIMIT 1`). The panel's own value
query reads the same table the same way, so title and figures are meant to describe the
same snapshot.

The two variables are configured with `refresh: 1` ("On Dashboard Load"), while the
dashboard itself auto-refreshes every 30 minutes (`"refresh": "30m"`). Grafana panel
queries re-run on that timer; "on load" variables do not. On a dashboard left open across
a `cost_forecast_refresh` run (daily at 04:00, or across a billing-period rollover), the
panel's bar-gauge values pick up the new row on the next 30-minute tick while the title's
date range stays pinned to whatever was current when the page was last loaded — the title
and the numbers can describe two different billing periods.

Confirmed live against the production Pi (`energy-monitor-db`): as of 2026-08-07 04:00,
the newest `cost_forecast` row is for billing period 2026-08-05 → 2026-09-04 (£3.47
actual / £139.98 projected), but a dashboard tab open since before that run would still
show the prior period, 2026-07-05 → 2026-08-04, in its title.

## Solution

Change `billing_period_start` and `billing_period_end` to `refresh: 2` ("On Time Range
Change"). Grafana re-evaluates "on time range change" variables whenever the dashboard's
time range object changes, which includes every auto-refresh tick for a relative time
range (this dashboard uses `now-3h` to `now+48h`) — so the title resyncs on the same
30-minute cadence the panel's own values already follow, without requiring a manual page
reload.

## User Stories

1. As the dashboard viewer, I want the billing-period title to always describe the same
   period as the numbers below it, so that I don't misread stale figures as belonging to
   the wrong period (or vice versa) during a long-lived browser tab.
2. As the operator, I want this fix to require no manual reload discipline, so that the
   dashboard stays trustworthy for anyone glancing at it, not just people who know to
   refresh the page after 04:00.

## Implementation Decisions

- **File**: `grafana/dashboard.json` only.
- **Change**: for the `billing_period_start` and `billing_period_end` template variable
  definitions, change `"refresh": 1` to `"refresh": 2`. No other field on either variable
  changes.
- **Scope confirmed via grep**: `$billing_period_start`/`$billing_period_end` are
  referenced in exactly one place in the dashboard — the panel title string
  (`"Billing Period Progress ($billing_period_start → $billing_period_end)"`). Neither
  variable feeds a query `WHERE` clause anywhere, so this change cannot alter any query
  result — only when the title string re-renders.
- **`region` variable is untouched** — it stays `refresh: 1`. It isn't time-dependent
  (it lists distinct regions from `product_rate`, which doesn't change on a 30-minute
  cadence), so there's no staleness problem to fix there, and switching it to
  `refresh: 2` would just be unnecessary extra query load on every auto-refresh tick.
- **The panel's own value query is unchanged.** It already re-runs on the dashboard's
  30-minute auto-refresh like any normal panel query; it was never the stale part.
- No Python/application code changes, no schema changes, no changes to
  `cost_forecast_refresh`'s scheduling or logic.

## Testing Decisions

- No automated test suite covers Grafana dashboard config in this repo (consistent with
  prior Grafana-only fixes, e.g. `bugfix-grafana-agile-forecast-precedence`). Verification
  is by deploying and observing the live dashboard on `pi-desktop`'s Grafana instance:
  confirm the title's date range updates on the next auto-refresh tick after a new
  `cost_forecast` row lands, without a manual page reload.
- No further test seam exists for this change — it's a single JSON field value with a
  single Grafana-documented effect (variable refresh trigger), not application logic.

## Out of Scope

- Any change to how `billing_period_start`/`billing_period_end` are queried (still
  `ORDER BY computed_at DESC LIMIT 1` against `cost_forecast`).
- Any change to the panel's value query, display thresholds, or gauge configuration.
- The degenerate-forecast edge case where `cost_forecast_refresh` computes actual ==
  projected for an already-ended billing period when Kraken's "current billing period"
  hasn't rolled over yet — this is documented, self-correcting behavior in
  `CostForecastRetriever._current_electricity_agreement`, not a defect this change
  addresses.
- Reworking the variable pickers' dropdown appearance (each currently only ever offers
  one option, since the underlying query is `LIMIT 1`) — confirmed with the user as out
  of scope for this fix.

## Further Notes

Diagnosed via a live query against the production Pi (`ssh pi@pi-desktop`,
`energy-monitor-db` container): `job_run` showed `cost_forecast_refresh` succeeding on
schedule (including 2026-08-07 04:00:05), and running the panel's exact SQL live returned
the correct, current-period values — confirming the panel query itself was never wrong.
The user's original screenshot was a stale Grafana panel-edit-mode cache, not a live
query result.
