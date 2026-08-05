# Decouple Agile Forecast Refresh from Cost Forecast

## Problem Statement

The daily Cost Forecast job fetches the Agile price forecast from agilepredict.com as
part of the same call that recomputes and writes `cost_forecast`. When agilepredict.com
had a multi-hour outage on 2026-08-04, the whole job failed after exhausting its retry
budget (~26 minutes), and `cost_forecast` went stale until the next scheduled run — even
though only the forecast-fetch half of the job actually failed. The two concerns (fetching
a forecast, computing today's cost projection) have different natural cadences and
different failure characteristics, but are currently bound to fail or succeed together.

## Solution

Split forecast-fetching onto its own hourly job, decoupled from the daily cost
projection. The hourly job tries agilepredict.com first, falls back to `api.x2r.uk` on
failure, and upserts whatever it gets into `agile_forecast`. The existing daily job keeps
computing `cost_forecast` exactly as it does today, but reads whatever is currently
stored in `agile_forecast` instead of fetching live — so an outage of one or both forecast
sources no longer blocks same-day cost projection, and a bad forecast-fetch hour is
retried independently on its own schedule rather than dragging down the cost job's retry
budget.

## User Stories

1. As the operator, I want Agile forecast fetching to run on its own hourly schedule, so
   that an agilepredict.com/x2r.uk outage doesn't also block the daily cost projection.
2. As the operator, I want the hourly forecast job to fall back to a second source
   (x2r.uk) when agilepredict.com fails, so that a single upstream outage doesn't leave
   `agile_forecast` stale for hours.
3. As the operator, I want the daily cost forecast job to keep working off whatever
   forecast data is currently stored, so that it never fails purely because a live
   forecast fetch failed.
4. As the operator, I want a fresh deployment to have a populated `agile_forecast` table
   before the first cost projection ever runs, so that a new install doesn't compute an
   Agile customer's projection against an empty forecast.
5. As the operator, I want the hourly job's outcome recorded via the existing `job_run`
   health-panel pattern, so that a forecast-fetch failure (from both sources) is visible
   the same way every other job's failure already is.

## Implementation Decisions

- **New `AgileForecastRetriever`** (`app/data/cost_forecast.py`'s sibling, likely
  `app/data/agile_forecast.py`), mirroring the existing `CostForecastRetriever` /
  `PricingRetriever` shape: a small class with a `refresh(as_of=None)` method and its own
  DI protocol (`AgileForecastSource`, `Protocol`) requiring `region_code`,
  `fetch_agile_forecast(region)` (primary, agilepredict.com), `fetch_agile_forecast_fallback(region)`
  (x2r.uk), and `persist_agile_forecast(region, readings, fetched_at)`.
  - `refresh()` tries the primary fetch; on any exception, tries the fallback; if both
    fail, lets the exception propagate (so the existing `_with_backoff_recording`
    wrapper in `main.py` retries with exponential backoff and records the job_run
    failure, same as every other job — no new retry/backoff logic needed here).
  - **Mutual exclusivity is load-bearing, not incidental**: exactly one source's
    readings are ever persisted per tick — the fallback fetch/persist must never run
    once the primary fetch has already succeeded. `agile_forecast` has no `source`
    column and none is being added; the upsert-by-(region, period_from) key means
    whichever write happens last for a slot is what's there, so a bug that let both
    fetches persist in the same tick (or that called the fallback unconditionally
    alongside the primary) would risk x2r.uk's numbers silently clobbering
    agilepredict.com's for that tick. Sequential try/except (fallback only reachable
    via the primary's `except` branch) is what guarantees this, not a convention to
    maintain elsewhere. Across *separate* ticks, agilepredict.com recovering and
    overwriting slots x2r.uk filled in during an outage is fine and expected — that
    direction is agilepredict.com reasserting itself as primary, not x2r.uk overwriting
    it.
  - No structural tracking of *which* source served a given fetch — a single
    pass/fail `job_run` entry per job, consistent with every other job. A log line at
    the point of falling back is sufficient for manual debugging.

- **`CostForecastRetriever` changes** (`app/data/cost_forecast.py`):
  - `CostForecastSource` protocol loses `fetch_agile_forecast` and
    `persist_agile_forecast`, gains `read_agile_forecast(region, as_of) -> list[AgileForecastReading]`.
  - `_project_agile_variable_cost` calls `read_agile_forecast` instead of
    `fetch_agile_forecast`, and no longer calls `persist_agile_forecast` (persistence is
    now exclusively the hourly job's responsibility). The rest of the method (tiling,
    the `as_of <= r.period_from < end_datetime` filter) is unchanged — the read call is a
    drop-in replacement for the old fetch call, same `list[AgileForecastReading]` shape.

- **New read path**:
  - `MariaDBClient.read_agile_forecast(region, as_of) -> list[AgileForecastReading]`:
    all `agile_forecast` rows for `region` with `period_from >= as_of`, ordered by
    `period_from`. No freshness/age check — returns whatever's there regardless of how
    old `fetched_at` is; staleness is surfaced via the hourly job's own `job_run` entry,
    not re-derived here.
  - `MonitoringClient.read_agile_forecast(region, as_of)` (`app/data/base.py`) delegates
    to it, fulfilling `CostForecastSource`'s new protocol method.

- **New x2r.uk client** (`app/data/octopus/x2r.py`), mirroring `agile_predict.py`'s
  shape: own Pydantic model for the nested `prices.forecast`/`day_ahead`/`actual`
  response shape (`date`/`price` fields, VAT-inclusive p/kWh, `Europe/London` ISO8601
  timestamps per the research doc), own mapping into `AgileForecastReading`
  (`period_to = period_from + 30min`, matching `AgilePredictClient`'s convention), same
  `@retry()` decorator convention, `GET https://api.x2r.uk/agile/{region}`. Reads from
  `prices.forecast` (forward-looking readings) — `day_ahead`/`actual` aren't relevant to
  a forecast fetch.
  - `MonitoringClient` gains an `_x2r` client instance and a
    `fetch_agile_forecast_fallback(region)` method delegating to it, fulfilling
    `AgileForecastSource`'s fallback method.

- **New job registration** (`app/main.py`):
  - `AGILE_FORECAST_REFRESH_JOB = "agile_forecast_refresh"` constant.
  - `register_agile_forecast_refresh_job(scheduler, agile_forecast, mariadb)` using the
    existing `_schedule_refresh_job` helper, `s.every(1).hours` cadence (matching the
    "hourly" requirement; distinct from `refresh_config.refresh_interval`, which governs
    consumption/pricing cadence and isn't necessarily 1 hour).
  - `run_initial_agile_forecast_sync(agile_forecast)` mirroring
    `run_initial_pricing_sync`'s shape (try/except, log-and-continue on startup
    failure), called in `main()` **before** `run_initial_cost_forecast_sync`, so
    `agile_forecast` is populated at least once before the first cost projection ever
    runs (fresh-install case).
  - `register_agile_forecast_refresh_job` called in `main()` alongside the other
    `register_*` calls.

- **ADR 0002 amendment** (already applied during design): documents the x2r.uk fallback
  and the hourly/daily cadence split as additive to the original public-API-consumption
  decision, not a reversal.

- **Domain glossary** (already applied during design): `.agent-docs/context.md` updated
  — "Agile Predict" entry now describes it as the primary source specifically; new
  "x2r.uk" and "Agile Forecast Refresh" entries added; "Cost Forecast" and "Job Run"
  entries updated to reflect the read-not-fetch relationship and the new job name.

## Testing Decisions

- **`AgileForecastRetriever`** tested at the same seam as `CostForecastRetriever`
  (`tests/test_cost_forecast_retriever.py`'s `_RealCostForecastSource` pattern): a new
  `tests/test_agile_forecast_retriever.py` with a `_RealAgileForecastSource` fake
  implementing `AgileForecastSource` against a real `MariaDBClient`/SQLite fixture, HTTP
  mocked via `responses` for both `agilepredict.com` and `api.x2r.uk` endpoints. Cases:
  primary succeeds (fallback never called); primary fails, fallback succeeds and its
  readings are persisted; both fail (exception propagates, nothing persisted).
- **New x2r.uk client** tested the same way as `tests/test_agile_predict_client.py`:
  a `tests/test_x2r_client.py` mocking `GET https://api.x2r.uk/agile/{region}` via
  `responses`, asserting the `prices.forecast` → `AgileForecastReading` mapping
  (field names, VAT-inclusive rate, 30-minute `period_to` derivation) and that a
  non-2xx/malformed response raises the same `APIError` convention as `AgilePredictClient`.
- **`MariaDBClient.read_agile_forecast`** tested directly against the SQLite fixture:
  region filtering, `period_from >= as_of` filtering, ordering.
- **`CostForecastRetriever`** existing tests updated: the two tests currently asserting
  on live agilepredict.com HTTP mocking (`test_agile_tariff_remaining_days_within_the_real_forecast_horizon`'s
  `agile_forecast` persistence assertion, `test_agile_predict_unreachable_raises_and_writes_no_row`)
  are updated to seed `agile_forecast` directly instead of mocking the HTTP endpoint —
  `test_agile_predict_unreachable_raises_and_writes_no_row` is removed outright (that
  failure mode no longer exists on `CostForecastRetriever`'s side; its equivalent moves
  to the new `AgileForecastRetriever` test file as the "both sources fail" case). Every
  other existing `_RealCostForecastSource`-based test keeps working unchanged once the
  fake's `fetch_agile_forecast`/`persist_agile_forecast` methods are replaced with
  `read_agile_forecast` seeding real `agile_forecast` rows up front instead of mocking
  HTTP.
- **Scheduler registration** tested in `tests/test_refresh_scheduling.py`, mirroring the
  existing hourly-pricing and daily-cost-forecast test shapes: job registered on an
  hourly interval; successful run recorded as a successful `job_run`; a persistently
  failing run (both sources failing) retries with exponential backoff and is recorded as
  a failed `job_run`; `run_initial_agile_forecast_sync` doesn't propagate a startup
  failure.

## Out of Scope

- `agileforecast.co.uk` as a third source — rejected in the research doc (no
  identifiable maintainer/repo to vet).
- Dropping third-party forecasting entirely in favor of Octopus's own ~1-2 day rate —
  considered and explicitly not chosen for this implementation (see grill session).
- Pruning/retention changes to `agile_forecast` — moving from twice-daily to hourly
  writes doesn't change its growth rate (upsert-by-time-slot already overwrites future
  slots in place; net new rows per day is unchanged, just recomputed more often).
- Per-source observability (tracking which of the two sources served a given fetch) —
  explicitly decided against; a single pass/fail `job_run` entry is enough.
- Any change to `tile_forecast_beyond` or the tiling algorithm itself.

## Further Notes

Full source research (live-confirmed Octopus/Elexon/NESO/Nord Pool horizon limits, the
`agile_predict` maintainer's own outage postmortem, x2r.uk's documented API shape) is in
`.agent-docs/research/agile-forecast-fallback-sources.md`.
