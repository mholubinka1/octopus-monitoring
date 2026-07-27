# Issues: bugfix-grafana-query-half-open-window

## Fix double-counted cost from inclusive-both-ends BETWEEN joins

**GitHub issue**: #434

**Blocked by**: None

**User stories**: 1, 2

### What to build

In `grafana/mariadb/queries.md`, replace every `c.period_from BETWEEN valid_from AND COALESCE(valid_to, '9999-12-31 23:59:59')` join condition (against both `product_rate` and `agreement`) with the half-open equivalent: `c.period_from >= valid_from AND c.period_from < COALESCE(valid_to, '9999-12-31 23:59:59')`. Apply to all six affected queries: Yesterday's Cost, Half-hourly Cost, p/kWh Efficiency vs Day's Avg Rate, Daily Average Cost, Standing Charge vs Unit-Rate Cost Split, Gas Cost (two occurrences each — one per join). Add a short standing note near the file's "Schema assumed" section documenting the half-open convention for future panels.

### Acceptance criteria

- [x] All twelve `BETWEEN`-pattern occurrences (six queries × two joins each) are corrected to the half-open form
- [x] Queries that don't join `consumption` to `product_rate`/`agreement` are untouched
- [x] A standing note documents the half-open convention for future additions to the file
- [x] The corrected join no longer fans out (48 rows for a 48-half-hour day, not 96) and the Yesterday's Cost query computes £3.19 for the reference day — verified independently, directly against MariaDB via `docker exec`, bypassing Grafana entirely (£2.7990 unit-rate cost + £0.3954 standing charge = £3.1944 → £3.19, matching the Grafana panel exactly)

**Note — unresolved residual gap, tracked separately, not part of this fix's scope.** The official Octopus app shows £3.25 for the same day, £0.06 above the verified £3.19. Investigated and ruled out as: a stale stored standing charge (confirmed the stored 40p/day matches the app), and a MariaDB server clock/timezone skew (investigated via `docker exec date -u` and direct `UTC_TIMESTAMP()` queries and conclusively disproven — the server clock is correct). Boundary-shift testing (0h/-1h/+1h UTC-day windows: £3.19/£3.31/£3.13) didn't land on £3.25 either, and no valid timezone convention produces the fractional-hour shift that would be needed to. Most likely a data-accuracy/freshness question (e.g. late-arriving smart-meter revisions) between this app's stored `consumption`/`product_rate` data and Octopus's own billing engine — a candidate for its own future investigation into the core app's data ingestion, not this file's queries.

---
