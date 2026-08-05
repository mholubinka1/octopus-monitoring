# Issues: bugfix-grafana-agile-forecast-precedence

> Work complete — PR ready to merge.

## Give Octopus actual rates precedence over stale AgilePredict forecast in the Agile Prices panel

**GitHub issue**: #467

**Blocked by**: None

**User stories**: 1, 2, 3

### What to build

Fix the "Agile Prices: Today/Tomorrow (Actual + Forecast)" panel (id 3) so it never
plots both an `actual` (`product_rate`) and a `forecast` (`agile_forecast`) point for the
same half-hour. Add a `NOT EXISTS` precedence filter to the forecast branch of the
existing `UNION ALL` query, in both `grafana/mariadb/queries.md` and the matching panel's
`rawSql` in `grafana/dashboard.json`, keeping the two byte-for-byte identical per this
repo's existing convention. Update `queries.md`'s prose for panel id 3 to document the
new precedence behaviour, matching how panel id 13 (Cheapest Time Window) already
documents its own equivalent filter. No other panel needs a change — confirmed via grep
that only id 3 and id 13 read `agile_forecast`.

### Acceptance criteria

- [x] Running the corrected query against the production Pi's `energy-monitor-db`
      (region `C`) returns no `period_from`/`valid_from` timestamp more than once across
      the `actual` and `forecast` series combined.
- [x] Wherever `product_rate` has a row for a half-hour, that half-hour's `agile_forecast`
      row is excluded from the result.
- [x] The `actual`/`forecast` series tagging is unchanged for rows that do appear.
- [x] `grafana/mariadb/queries.md`'s SQL block for panel id 3 and `grafana/dashboard.json`'s
      `rawSql` for panel id 3 are identical after the edit.
- [x] `queries.md`'s prose for panel id 3 describes the precedence behaviour.
- [x] No other panel or query in either file is changed.

---
