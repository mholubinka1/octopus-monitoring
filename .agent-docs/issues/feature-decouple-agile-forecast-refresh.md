# Issues: feature/decouple-agile-forecast-refresh

## x2r.uk fallback forecast client (#469)

**Blocked by**: None

**User stories**: 2

### What to build

A new client for `api.x2r.uk`'s documented Agile forecast API, mirroring
`AgilePredictClient`'s shape (`app/data/octopus/agile_predict.py`): its own Pydantic
model for x2r.uk's response shape (a single object with `region`, `region_name`, and
nested `prices.forecast`/`day_ahead`/`actual` arrays, each entry `{"date": ..., "price":
...}` — VAT-inclusive p/kWh, `Europe/London` ISO8601 timestamps), and a mapping from
`prices.forecast` entries into `AgileForecastReading` (`period_to = period_from +
30min`, matching `AgilePredictClient`'s convention). Same `@retry()` decorator
convention and `APIError` failure contract as the existing client, so it's a drop-in
peer that a caller can treat identically to `AgilePredictClient.get_forecast`.

### Acceptance criteria

- [ ] `X2rClient.get_forecast(region)` returns `list[AgileForecastReading]` mapped from
      `prices.forecast`, ignoring `day_ahead`/`actual`.
- [ ] A non-2xx response or a response with no `prices.forecast` entries raises
      `APIError`, matching `AgilePredictClient`'s existing failure convention.
- [ ] Individual fetch attempts are retried via `@retry()`, same as `AgilePredictClient`.
- [ ] `tests/test_x2r_client.py` covers: successful mapping (field names, VAT-inclusive
      rate, 30-minute `period_to` derivation), and the empty/error-response failure case.

---

## Agile Forecast Refresh: hourly job with primary/fallback orchestration (#470)

**Blocked by**: #469

**User stories**: 1, 2, 4, 5

### What to build

A new `AgileForecastRetriever` (mirroring `CostForecastRetriever`/`PricingRetriever`'s
shape) with its own DI protocol (`AgileForecastSource`) and a `refresh(as_of=None)`
method: fetch from agilepredict.com; on any exception, fetch from x2r.uk instead; if
both fail, propagate the exception. Persist whichever source's readings were fetched —
never both in the same tick (see spec's "mutual exclusivity is load-bearing" note; the
sequential try/except is what guarantees this, not a convention to maintain elsewhere).

`MonitoringClient` gains the `_x2r` client instance and a `fetch_agile_forecast_fallback`
method delegating to it, fulfilling the new protocol's fallback method (its existing
`fetch_agile_forecast`/`persist_agile_forecast` are reused unchanged for the primary
path and persistence).

Register a new hourly job in `main.py` (`AGILE_FORECAST_REFRESH_JOB =
"agile_forecast_refresh"`, `s.every(1).hours`, using the existing
`_schedule_refresh_job` helper — same retry-with-backoff and `job_run` recording every
other job already gets, no new scheduling infrastructure). Add
`run_initial_agile_forecast_sync` (mirroring `run_initial_pricing_sync`'s log-and-continue
shape), called in `main()` **before** `run_initial_cost_forecast_sync`, so a fresh
install has a populated `agile_forecast` table before the first cost projection ever
runs.

At this point `CostForecastRetriever` is untouched — it keeps its own live fetch/persist
exactly as today. This slice is independently demoable: `agile_forecast` now gets
refreshed hourly, with automatic fallback, regardless of what the daily cost job does.

### Acceptance criteria

- [ ] `AgileForecastRetriever.refresh()` fetches from agilepredict.com and persists on
      success; x2r.uk is never called when agilepredict.com succeeds.
- [ ] On agilepredict.com failure, `AgileForecastRetriever.refresh()` fetches from
      x2r.uk and persists its readings instead.
- [ ] When both sources fail, the exception propagates and nothing is persisted.
- [ ] `AGILE_FORECAST_REFRESH_JOB` is registered on an hourly interval; a successful run
      is recorded as a successful `job_run`; a persistently failing run (both sources
      failing) retries with exponential backoff and is recorded as a failed `job_run`.
- [ ] `run_initial_agile_forecast_sync` runs at startup, before
      `run_initial_cost_forecast_sync`, and does not propagate a startup failure (logs
      and continues, matching every other `run_initial_*_sync`).
- [ ] `tests/test_agile_forecast_retriever.py` covers the three fetch-orchestration
      cases above at the same DI-protocol seam `test_cost_forecast_retriever.py` uses.
- [ ] `tests/test_refresh_scheduling.py` covers hourly registration, success/failure
      `job_run` recording, and the startup-sync-swallows-failure case, mirroring the
      existing hourly-pricing and daily-cost-forecast test shapes.

---

## Cost Forecast reads stored forecast instead of fetching live (#471)

**Blocked by**: #470

**User stories**: 1, 3

### What to build

Cut `CostForecastRetriever` over from fetching agilepredict.com live to reading
whatever's currently stored in `agile_forecast`. Add
`MariaDBClient.read_agile_forecast(region, as_of)` (all rows for the region with
`period_from >= as_of`, ordered by `period_from` — no freshness/age check, returns
whatever's there regardless of how old `fetched_at` is) and the corresponding
`MonitoringClient.read_agile_forecast` delegate. Update `CostForecastSource`'s protocol:
remove `fetch_agile_forecast`/`persist_agile_forecast`, add `read_agile_forecast`.
`_project_agile_variable_cost` calls the new read method instead of the old fetch call
and no longer persists (persistence is now exclusively the hourly job's responsibility,
handled by the previous issue) — the rest of the method (tiling, the
`as_of <= r.period_from < end_datetime` filter) is unchanged, since the read call
returns the same `list[AgileForecastReading]` shape the old fetch call did.

This is the actual outage fix: once this lands, an agilepredict.com/x2r.uk outage can no
longer fail the daily cost forecast job, because it no longer talks to either service.

### Acceptance criteria

- [ ] `MariaDBClient.read_agile_forecast(region, as_of)` returns rows for the region
      with `period_from >= as_of`, ordered by `period_from`.
- [ ] `CostForecastRetriever` no longer calls agilepredict.com (or any HTTP endpoint)
      for the Agile forecast; it reads from `agile_forecast` via the new method.
- [ ] `CostForecastRetriever` no longer persists to `agile_forecast` (the hourly job
      from slice #2 is the sole writer).
- [ ] Every existing `_project_agile_variable_cost`/tiling behavior (real-forecast
      window, tiling beyond the stored horizon, inclusive billing-period-end pricing)
      is unchanged and covered by the existing `tests/test_cost_forecast_retriever.py`
      suite, updated to seed `agile_forecast` directly instead of mocking
      agilepredict.com's HTTP endpoint.
- [ ] `test_agile_predict_unreachable_raises_and_writes_no_row` is removed from
      `test_cost_forecast_retriever.py` (that failure mode no longer exists on this
      class — its equivalent already exists as the "both sources fail" case added in
      slice #2's `test_agile_forecast_retriever.py`).
- [ ] A new `tests/test_read_agile_forecast.py`, mirroring the existing
      `tests/test_read_current_product_rate.py` convention (one file per MariaDBClient
      read method), covers `read_agile_forecast`'s region and `period_from >= as_of`
      filtering directly against the SQLite fixture.

---
