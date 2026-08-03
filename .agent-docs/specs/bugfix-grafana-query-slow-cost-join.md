# Grafana Query Fixes: Slow product_rate Join, Stale Retention Windows, Daily Cost Trend Panels

## Problem Statement

Three related problems sat in `grafana/mariadb/queries.md`, the reference SQL hand-copied into Grafana's query editor:

1. Every panel joining `consumption` to `product_rate` used a range-predicate join (`c.period_from >= pr.valid_from AND c.period_from < COALESCE(pr.valid_to, ...)`). Confirmed live against production (4,199 `consumption` rows × 37,075 `product_rate` rows), this join can't use the composite index — MariaDB falls back to a full Block Nested Loop scan on both tables. The p/kWh Efficiency panel's query alone took 88.9s.
2. Five panels claimed lookback windows (90 days, 12 weeks/84 days) that `consumption` can never actually satisfy — the table's startup backfill only ever pulls `retention_days` (45 days) of history, so those panels were silently returning less data than their own titles claimed.
3. There was no panel showing the most recent day's cost as a standalone, clearly-dated headline number — "Yesterday's Cost" answers a different, narrower question (the most recent *complete* day within the last 7 days specifically), and no other panel gives a longer-range cost trend at a glance.

## Solution

1. Rewrite every `consumption`-to-`product_rate` join as a correlated subquery (find the single most-recent `product_rate` row with `valid_from <= X`, `ORDER BY valid_from DESC LIMIT 1`) instead of the range-predicate form. Confirmed live: same query, same results, 11.8s instead of 88.9s for the p/kWh Efficiency panel.
2. Fix the five affected panels' windows down to 45 days, and add a shared explanatory paragraph in the file's conventions section documenting *why* 45 days is the real ceiling, so future panels don't reintroduce a longer, silently-truncated window.
3. Add two new panels: **Daily Cost Trend — Last 45 Days** (a Stat panel with a line-graph sparkline, reduced to the most recent complete day's cost over a 45-day series) and **Daily Cost Trend — As Of Date** (a companion Stat panel showing just the date that number belongs to, so the headline cost is never shown without its date).

All three pieces ship together on this branch/PR — the retention-window fix and the two new panels are drafted together already, and splitting them apart now would just be churn for no review benefit.

## User Stories

1. As the dashboard owner, I want every `consumption`-to-`product_rate` join to use an indexed lookup, so that panels using that join load in seconds rather than tens of seconds.
2. As the dashboard owner, I want every panel's stated lookback window to match what `consumption`'s actual retention allows, so that a panel's title never overstates how much history it's actually showing.
3. As the dashboard owner, I want a headline "cost trend" figure that's always shown next to the date it belongs to, so I never mistake an older complete day's cost for a more recent one.
4. As a future reader of `queries.md`, I want the shared retention-window paragraph to explain why 45 days is the real ceiling (not 90 or 84), so nobody reintroduces a longer window that gets silently truncated.
5. As a future reader of `queries.md`, I want the correlated-subquery join pattern applied consistently everywhere `product_rate` is joined, so nobody re-adds the slow range-predicate form to a new panel by copying an old one.

## Implementation Decisions

- **File touched**: `grafana/mariadb/queries.md` only — same as the heatmap panel work, no application code, schema, or dashboard JSON exists for these panels.
- **Join rewrite**: applied to all six panels that join `consumption` to `product_rate` (Yesterday's Cost, Half-hourly Cost, p/kWh Efficiency, Daily Average Cost 7-Day Rolling, Standing Charge vs Unit-Rate Cost Split, Gas Cost) plus the two new Daily Cost Trend panels — verified via direct grep that no range-predicate join against `product_rate` remains anywhere in the file.
- **Retention-window paragraph**: added once, in the shared conventions section near the existing join-performance note — not duplicated per-panel. Confirmed only one occurrence in the file after this branch was rebased onto the now-merged heatmap-panel branch (`main`), since both touched adjacent prose in the same section.
- **Window fixes**: p/kWh Efficiency (90 → 45 days), Day-of-Week Average Consumption (84 → 45 days, title updated from "12 Weeks" to "45 Days"), both 7-Day Rolling Average panels — Usage and Cost — (84 → 45 days, same title update). The Consumption Heatmap panel is *not* touched here — it already reflects the 45-day window and native-Heatmap-panel fix merged via PR #458.
- **Daily Cost Trend panels**: both reuse the identical CTE (including the completeness guard) rather than one reading the other's result, since Grafana panels can't share a query result across panels. The "As Of Date" panel exists specifically so the cost figure is never displayed without the date it applies to, given the completeness guard means "most recent complete day" can silently be more than a few days back if there's a longer gap in `consumption`.
- **No ADR**: the join rewrite is a real, non-obvious performance trade-off, but it's already fully explained inline in the file's existing "product_rate join performance" convention note (added by a prior panel's fix) — this branch just applies that established pattern more broadly, it doesn't introduce a new decision.

## Testing Decisions

Documentation-only change to a Markdown file containing reference SQL — no application code, no test suite, no CI surface for Grafana panel definitions in this repo. Verification is manual: paste each changed/new query into Grafana's query editor and confirm it runs and renders as described. No automated test applies or is in scope, matching the same testing decision made for the Consumption Heatmap panel work (PR #458).

## Out of Scope

- The Consumption Heatmap panel — already fixed and merged via PR #458; this branch must not reintroduce or modify it.
- Any change to `daily_consumption_summary`-backed panels (Yearly Comparison, Row 4) — unaffected by the 45-day raw-`consumption` retention cap, since they read a separate, pruning-exempt table.
- A pruning job that actually deletes `consumption` rows older than 45 days — per `.agent-docs/context.md`'s Retention Window entry, no such job exists yet; this branch only documents the *effective* ceiling `retention_days` already imposes via the startup backfill, it doesn't add enforcement.
- Any Grafana panel/version change beyond what's already described — no new panel types, no transforms, no upgrade.

## Further Notes

The join-performance fix (commit `8ed768d`, already on this branch) predates the retention-window and new-panel work; all three were rebased cleanly onto the now-merged `main` (post PR #458 and PR #461) with zero file-level conflicts against either of those merged PRs.
