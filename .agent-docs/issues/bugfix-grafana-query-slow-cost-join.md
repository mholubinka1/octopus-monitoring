# Issues: bugfix/grafana-query-slow-cost-join

> Work complete — PR ready to merge.

## Fix retention-window claims and add Daily Cost Trend panels

**GitHub issue**: #462

**Blocked by**: None

**User stories**: 2, 3, 4, 5

### What to build

In `grafana/mariadb/queries.md`: add the shared "Row 2 lookback windows are capped at the retention window (45 days)" paragraph explaining why `consumption` never actually holds more than 45 days of history; fix the four affected panels' windows down to 45 days (p/kWh Efficiency, Day-of-Week Average Consumption, both 7-Day Rolling Average panels — Usage and Cost — each with their title updated to say "45 Days" instead of "12 Weeks"/"84 Days"); and add two new panels, "Daily Cost Trend — Last 45 Days" (Stat panel, line-graph sparkline, most recent complete day's cost over a 45-day series) and "Daily Cost Trend — As Of Date" (companion Stat panel showing just the date that cost belongs to, so the headline number is never shown without its date). Both new panels reuse the correlated-subquery join pattern and completeness-guard convention already established elsewhere in the file. The Consumption Heatmap panel is not touched — it's already correct, merged via PR #458.

Note: the join-performance fix itself (range-predicate → correlated-subquery join against `product_rate`, applied across six panels) is already committed on this branch as `8ed768d` and does not need further work — this issue covers only the uncommitted diff on top of it.

### Acceptance criteria

- [x] Shared "Row 2 lookback windows..." paragraph present exactly once, explaining the 45-day ceiling.
- [x] p/kWh Efficiency, Day-of-Week Average Consumption, and both 7-Day Rolling Average panels all use `INTERVAL 45 DAY` (not 90 or 84), with titles updated to say "45 Days".
- [x] "Daily Cost Trend — Last 45 Days" panel added: Stat panel, line-graph sparkline, `Last (not null)` reducer, correlated-subquery join, completeness guard, 45-day window.
- [x] "Daily Cost Trend — As Of Date" panel added: companion Stat panel, same underlying CTE, reduced to `MAX(time) AS as_of_date`.
- [x] No range-predicate join against `product_rate` remains anywhere in the file (verify via grep for `pr.valid_to`/`>= pr.valid_from`).
- [x] Consumption Heatmap panel unchanged from its PR #458-merged state.

---
