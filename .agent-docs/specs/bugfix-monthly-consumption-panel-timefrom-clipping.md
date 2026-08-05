# Fix Monthly Total Consumption and Weekly YoY panels clipping their oldest data point

## Problem Statement

The "Monthly Total Consumption" panel (`dashboard.json`, panel id 9) intermittently clips the bar for its furthest-back month from view. The effect worsens as the current date progresses through the month, and is worst in any 12-month span that crosses a leap day (29 February). The "Consumption Year-on-Year Percentage Change" panel (id 10) has the same class of exposure: its query's lookback is also calendar-based (52-53 ISO weeks) rather than a fixed day count.

## Solution

Both panels' `timeFrom` override, which sets their rendered x-axis window, assumed each query's lookback was a fixed 365 days. It isn't: panel 9's `WHERE` clause anchors to the first of the month 11 calendar months back, and calendar months vary in length, so the true lookback ranges from ~334 days (start of the current month) up to ~366 days (end of the current month, when a leap day falls within the 12-month span) — sometimes exceeding the fixed 365-day axis window and clipping the oldest bar. Panel 10's ISO-week-based lookback has the same kind of margin problem. Widening `timeFrom` to `400d` on both panels, comfortably past the 366-day worst case, removes the clipping without changing either query.

## User Stories

1. As the account holder, I want the Monthly Total Consumption panel to always show all 12 months' bars, so that a chart I check for seasonal trends doesn't silently lose its oldest data point depending on what day of the month it is.
2. As the account holder, I want the Weekly Year-on-Year panel to show its full 52-53 week range for the same reason, so it doesn't develop the same clipping bug at the edges of a leap year.
3. As a future reader of `grafana/mariadb/queries.md`, I want the documented `timeFrom` value to match the deployed panels and to explain why it's wider than a naive "12 months/52 weeks ≈ 365 days" guess, so a future edit doesn't reintroduce the narrower, clipping-prone value.

## Implementation Decisions

- `grafana/dashboard.json`: panel id 9 ("Monthly Total Consumption") and panel id 10 ("Consumption Year-on-Year Percentage Change") — `timeFrom` changes from `"365d"` to `"400d"` on both, applied as a targeted edit against the file already committed in the repo. Two further live-Grafana tweaks, unrelated to the clipping bug but also not yet reflected in the repo, were pulled in alongside it at the user's request: panel id 3's ("Agile Prices: Today/Tomorrow") `fillOpacity` 0 → 50, and panel id 12's ("Consumption Heatmap") `gridPos.h` 16 → 17. The live Grafana dashboard had drifted further still (several other in-Grafana edits reverting fixes already committed here — e.g. a slow-join fix and emoji encoding) — those were deliberately not pulled in; only the four values above changed.
- `grafana/mariadb/queries.md`: update the documented `timeFrom: 365d` notes for both panels (Row 4 section) to `400d`, with a short note that the value is deliberately wider than each query's nominal ~365-day lookback to give margin against calendar-month/ISO-week-length variation and leap years, not a rounding choice.
- No change to the SQL queries themselves (`DATE_SUB(date, INTERVAL DAYOFMONTH(date) - 1 DAY)` bucketing and the `DATE_FORMAT(CURDATE() - INTERVAL 11 MONTH, '%Y-%m-01')` cutoff for panel 9; the `YEARWEEK`-based logic for panel 10 — both already correct per `feature-yearly-consumption-comparison.md`).

## Testing Decisions

- No automated test. `grafana/dashboard.json` and `grafana/mariadb/queries.md` are Grafana-facing config/reference artifacts with no test harness in this repo, consistent with `bugfix-grafana-query-half-open-window`'s testing decision. Verification is visual, in Grafana, once deployed: confirm the oldest data point on both panels renders fully rather than being clipped.

## Out of Scope

- Any change to the underlying SQL queries — already correct.
- Any `app/` or `tests/` change — this is dashboard/doc only.

## Further Notes

Root cause diagnosed by walking the calendar-day arithmetic: for a 12 consecutive calendar-month span, total days = 365 in a non-leap span or 366 when a 29-February falls inside it. The panel's rendered x-axis lower bound is `now - timeFrom`, while the query's oldest-bucket timestamp is pinned to the 1st of the month 11 months back and only advances when the current month rolls over — so the gap between "now" and that fixed timestamp grows throughout the month, from ~334 days up to the 365/366-day span total minus one day. A `365d` override left zero margin against the leap-year case and shrinking-but-still-positive margin otherwise; `400d` gives a firm buffer in both cases.
