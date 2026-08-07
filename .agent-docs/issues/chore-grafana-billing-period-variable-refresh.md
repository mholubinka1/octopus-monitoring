# Issues: chore/grafana-billing-period-variable-refresh

## Resync billing-period title variables on auto-refresh

**GitHub issue**: #476

**Blocked by**: None

**User stories**: 1, 2

### What to build

In `grafana/dashboard.json`, change the `billing_period_start` and `billing_period_end`
template variables from `refresh: 1` ("On Dashboard Load") to `refresh: 2` ("On Time
Range Change"). This makes both variables re-evaluate on the dashboard's existing
30-minute auto-refresh (since the dashboard uses a relative time range, each auto-refresh
tick counts as a time range change), keeping the "Billing Period Progress" panel's title
in sync with its own value query — which already re-runs on that same 30-minute cadence.

No other variable, panel query, or application code changes.

### Acceptance criteria

- [ ] `billing_period_start` variable has `"refresh": 2` in `grafana/dashboard.json`
- [ ] `billing_period_end` variable has `"refresh": 2` in `grafana/dashboard.json`
- [ ] `region` variable is unchanged (`"refresh": 1`)
- [ ] No other field on either variable, and no panel query, changes
- [ ] Deployed and observed live: title's date range updates on the dashboard's normal
      auto-refresh tick after a new `cost_forecast` row lands, without a manual page
      reload

---
