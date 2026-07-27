# Issues: bugfix-grafana-query-half-open-window

## Fix double-counted cost from inclusive-both-ends BETWEEN joins

**GitHub issue**: #434

**Blocked by**: None

**User stories**: 1, 2

### What to build

In `grafana/mariadb/queries.md`, replace every `c.period_from BETWEEN valid_from AND COALESCE(valid_to, '9999-12-31 23:59:59')` join condition (against both `product_rate` and `agreement`) with the half-open equivalent: `c.period_from >= valid_from AND c.period_from < COALESCE(valid_to, '9999-12-31 23:59:59')`. Apply to all six affected queries: Yesterday's Cost, Half-hourly Cost, p/kWh Efficiency vs Day's Avg Rate, Daily Average Cost, Standing Charge vs Unit-Rate Cost Split, Gas Cost (two occurrences each — one per join). Add a short standing note near the file's "Schema assumed" section documenting the half-open convention for future panels.

### Acceptance criteria

- [ ] All twelve `BETWEEN`-pattern occurrences (six queries × two joins each) are corrected to the half-open form
- [ ] Queries that don't join `consumption` to `product_rate`/`agreement` are untouched
- [ ] A standing note documents the half-open convention for future additions to the file
- [ ] The corrected Yesterday's Cost query, re-run against the production database, returns £3.25 (matching the app's own cost display and Octopus Compare)

---
