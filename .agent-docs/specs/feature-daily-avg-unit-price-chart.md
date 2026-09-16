# Daily Average Unit Price (Rolling 7-Day Window) Dashboard Panel

## Problem Statement

The dashboard already shows a rolling 7-day view of **Daily Average Cost** and **Daily Average Usage**, but nothing shows how the *price per kWh* itself has been trending. On the Agile tariff the Unit Rate varies every half-hour, so a change in Daily Average Cost could come from using more energy, from paying a higher price per unit, or both — and today there's no panel that isolates the price component.

## Solution

Add a third rolling-7-day panel, **Daily Average Unit Price (Rolling 7-Day Window)**, showing the consumption-weighted price actually paid per kWh each day (excluding standing charge), smoothed over a trailing 7-day window, covering the same Last 45 Days as its two siblings.

## User Stories

1. As the dashboard viewer, I want to see the 7-day rolling average of what I actually paid per kWh, so that I can tell whether a cost change was driven by price or by usage.
2. As the dashboard viewer, I want this panel to reflect consumption-weighted price (not a flat average of the tariff's rate), so that it accurately represents what Agile's half-hourly price variation actually cost me, matching how Daily Average Cost is computed.
3. As the dashboard viewer, I want this panel visually grouped with Daily Average Cost and Daily Average Usage (left to right: Unit Price, Cost, Usage), so that the three related trends are easy to compare side by side.

## Implementation Decisions

- **File**: `grafana/dashboard.json` (dashboard JSON model) and `grafana/mariadb/queries.md` (query documentation) — no application code changes; this is a Grafana-only addition, consistent with how the two sibling panels were built.
- **Metric**: consumption-weighted daily unit price, `SUM(est_kwh * unit_rate) / SUM(est_kwh)`, excluding standing charge — distinct from a flat `AVG(unit_rate)` across the day's half-hours, which would misrepresent an Agile tariff's price by ignoring when power was actually used.
- **Query shape**: mirrors the existing Daily Average Cost / Daily Average Usage panels exactly — local-day bucketing via `CONVERT_TZ(..., 'UTC', 'Europe/London')`, the day-completeness `HAVING COUNT(*) = ...` guard, the correlated-subquery `product_rate` join (not the range-predicate form — see the performance note in `queries.md`), a 45-day (`Last 45 Days`) lookback (`c.period_from >= NOW() - INTERVAL 45 DAY`, `timeFrom: "45d"`), and a `ROUND(AVG(...) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2)` rolling 7-day average.
- **Scope**: Electricity only (`energy = 'E'`), matching both sibling panels — gas has no comparable half-hourly-varying-price motivation.
- **Field config**: `p/kwh` unit and threshold bands (light-blue < 0p, green ≥ 0p, yellow ≥ 10p, semi-dark-orange ≥ 20p, red ≥ 25p) reused verbatim from the existing Agile Prices panel, for visual consistency across every pence-per-kWh panel on the dashboard. `decimals: 2`, `min: -1` (allows the light-blue sub-zero band to render, since Agile pricing can go negative).
- **Layout**: added into the grid row at `y: 23`, leftmost of the three (new panel `id: 14`, `x: 10, w: 5`), followed by Cost (`id: 8`, narrowed from `x: 10, w: 7` to `x: 15, w: 4`) and then Usage (`id: 7`, narrowed from `x: 17, w: 7` to `x: 19, w: 5`) — left-to-right order Unit Price → Cost → Usage, per explicit user direction during the grill session (superseding an earlier "insert between Cost and Usage" framing floated before that decision). All three continue to exactly fill the row's `x: 10` to `x: 24` span.
- **Incidental reconciliation**: while syncing against a fresh live export of the dashboard (which had drifted to `version: 36` from the repo's `version: 19`, 17 unreconciled manual edits), one regression was found and corrected along the way — the live export's "Latest Consumption" panel cost query (id 4, query B) had reverted to the documented 88.9s-class range-predicate `product_rate` join. It was rewritten back to the correlated-subquery form already present in the repo's committed `dashboard.json` — so this correction produces **no diff** against `origin/main` (the committed file was never actually regressed; only the live Grafana export was). All other live drift (new annotation markers, dashboard time range widened to `+120h`, several threshold/legend/display-mode tweaks, a new axis-min override on panel 4) was carried over as-is and does appear in the diff. Full detail is in `queries.md`.

## Testing Decisions

- No new automated test. Neither sibling panel (`Daily Average Cost`, `Daily Average Usage`) has dedicated pytest coverage — `dashboard.json`'s panel SQL is Grafana-side only and isn't executed by the Python test suite. `test_cost_via_join.py` verifies the underlying `consumption` ⋈ `agreement` ⋈ `product_rate` join pattern in principle via SQLAlchemy, but not any specific panel's exact query, rolling-window logic, or weighting. This panel follows the same precedent: verified manually in Grafana once deployed.

## Out of Scope

- A Gas variant of this panel.
- A flat (non-consumption-weighted) unit price panel.
- Automated testing of Grafana panel SQL (no existing seam covers this class of change).
- Any other live-dashboard drift beyond the one performance regression called out above — the rest is carried over as observed, not re-litigated.

## Further Notes

The live dashboard export used for this reconciliation was `pi-desktop_ octopus-energy-1789556594328.json`, downloaded 2026-09-16. `queries.md` documents the full set of incidental changes discovered during the diff (thresholds, legend visibility, display modes, heatmap color scaling, annotation markers, dashboard-level time range) in their respective per-panel sections and the file's introductory notes.
