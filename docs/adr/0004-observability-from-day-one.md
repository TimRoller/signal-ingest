# ADR 0004: Observability from day one, not "later"

## Status
Accepted — 2026-05-24

## Context
"We'll add observability later" is the most common lie in engineering planning. "Later" tends to mean *after* the first production outage, *after* the first cost spike, *after* the first regression that took two days to diagnose because nobody could see what the system was doing.

By then, instrumenting the code is more painful than it would have been from the start, the team has built habits around blind debugging, and the dashboard nobody built leaves every question unanswered.

The cost of adding three packages and a `/metrics` endpoint at the start is trivial. The cost of adding them after the system is in production is high — measured in incidents, in MTTR, and in compounded operational debt.

## Decision

Every service in this repo emits, from its first commit:

1. **Prometheus metrics** at `/metrics` — request counts, durations (histogram), queue depth, LLM cost counters, validation pass/fail.
2. **OpenTelemetry traces** — every inbound request gets a trace; spans propagate across the FastAPI → Redis → Worker → Postgres → S3 boundary.
3. **Structured JSON logs** — single-line, parseable, including trace_id for correlation.

The local `docker-compose.yml` includes Prometheus and Grafana from Phase 1 (not Phase 6). Grafana dashboards (pipeline health, data quality, cost) are checked into `infra/grafana/` as JSON.

This is enforced at the **shared library** level (`shared/observability/`) — services don't choose whether to be observable; they import the helper and get it.

## Consequences

**Positive:**
- Every regression has a chart. Every cost spike has a dimension. Every slow request has a span.
- The system is debuggable in production from day one without ad-hoc instrumentation patches.
- Dashboards are versioned alongside the code that produces the metrics — they don't drift.

**Negative:**
- Boilerplate cost: every service has 10–20 lines of instrumentation init.
- Local dev stack is heavier — Prometheus + Grafana add ~200 MB of containers.
- Test setup must isolate the OTel exporter so unit tests don't hit a real backend.

## Mitigation
- The boilerplate lives in `shared/observability/init_otel.py` — one import per service, one call at startup.
- Local Prometheus + Grafana are opt-in via a `compose --profile observability` flag for engineers who don't want the overhead during pure-feature dev.

## Alternatives considered
- **Add it in Phase 6.** Rejected: every prior project that took this path regretted it.
- **Logging only, no metrics.** Rejected: logs are necessary but not sufficient — you cannot alert on rates or compute SLOs from them efficiently.
- **Vendor-managed APM (Datadog, New Relic) from day one.** Reasonable, but rejected for this project to keep dependencies local-first and avoid lock-in. OTel exports anywhere; we can graduate to a vendor later by changing one exporter URL.
