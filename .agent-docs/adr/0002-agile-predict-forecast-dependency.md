---
status: accepted
---

# Depend on agile_predict's public API for price forecasting

Cost forecasting needs a forward-looking view of Agile prices beyond Octopus's own day-ahead publication. Building that in-house means an ML pipeline (ensemble models, weather/demand/generation data feeds, scheduled retraining) — the approach taken by the open-source `agile_predict` project (fboundy/agile_predict), which already runs this pipeline and publishes 14-day-ahead forecasts per GSP region, hosted on Fly.io. We decided to consume that public API rather than port the model in-house: it avoids new ML dependencies (CatBoost/LightGBM/scikit-learn) and a data pipeline this project has no other need for, at the cost of a runtime dependency on a third-party free service with no uptime guarantee.

**Endpoint note** (added after `feature/agile-cost-forecast`'s research/smoke-testing): the JSON API lives at `https://agilepredict.com/api/{region}/` — `prices.fly.dev/v2/<region>/`, this ADR's original endpoint, now serves the project's HTML frontend instead of JSON at that path. Same underlying service and decision, corrected path only. See `.agent-docs/research/octopus-billing-period-api.md` for the live verification.

## Consequences

- Forecast data (and anything derived from it, e.g. cost projections) can go stale or unavailable if the upstream service is down or discontinued — the health panel (see `job_run` tracking) surfaces this rather than failing silently.
- No SLA exists with the upstream service; if it becomes unreliable or shuts down, the fallback is to drop cost forecasting or revisit building the pipeline in-house (see `agile_predict`'s architecture for a reusable feature/model reference at that point).

**Fallback source and decoupled cadence** (added after a multi-hour agilepredict.com outage on 2026-08-04 took the daily cost forecast down with it — see `.agent-docs/research/agile-forecast-fallback-sources.md`): forecast fetching moved to its own hourly job (Agile Forecast Refresh), separate from the daily cost-forecast job, which now reads whatever was last persisted instead of fetching live. On failure, Agile Forecast Refresh falls back to `api.x2r.uk` — another single-maintainer hobby service, independently hosted from agilepredict.com's Fly.io deployment, so an infrastructure-level outage of one doesn't take out the other. This mitigates *infrastructure* risk (one host going down), not *category* risk (neither source carries an SLA) — both remain within the trade-off already accepted above, not a new one. `agileforecast.co.uk` was considered and rejected as a fallback candidate: no identifiable maintainer or repo, so its reliability can't be vetted the way `agile_predict`'s and x2r.uk's public repos/self-descriptions allow.
