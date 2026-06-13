# Weather Data Aggregator — Error Handling Documentation

**Module 4 · Lab 4 | Author: Waqar Javed | Date: 2026-06-13**

---

## Architecture Overview

The program uses a three-layer error containment model:

```
fetch_weather()          ← Layer 1: pure I/O; always raises
      ↓
fetch_weather_safe()     ← Layer 2: catches & classifies; returns (data, failure)
      ↓
aggregate_weather()      ← Layer 3: orchestrates; never crashes
```

---

## Error Decision Table

| Exception | Where Caught | Retry? | Level | Rationale |
|---|---|---|---|---|
| `requests.Timeout` | `fetch_weather_safe` | ✓ Yes | WARNING | Transient; a retry on a slow server often succeeds. |
| `requests.ConnectionError` | `fetch_weather_safe` | ✓ Yes | WARNING | Transient; DNS hiccups and brief drops usually resolve quickly. |
| Other `requests.RequestException` | `fetch_weather_safe` | ✓ Yes | WARNING | Generic network issue; retrying is safe and cheap. |
| HTTP 4xx / 5xx (`ValueError` from `raise_for_status`) | `fetch_weather_safe` | ✗ No | WARNING | A 400 means bad input we control (bad coords); a 500 is server-side — retrying a 500 can make load worse. Fail fast. |
| `ValueError` (bad JSON body) | `fetch_weather_safe` | ✗ No | WARNING | If the server sends garbage, a retry won't fix it — same garbage comes back. |
| `KeyError` (missing API field) | `fetch_weather_safe` | ✗ No | WARNING | The API contract changed. Retrying won't produce the missing key. |
| `OSError` writing report | `save_report` | ✗ No | ERROR | Disk or permissions problem — re-raised so caller can exit(1). |
| Any uncaught exception | `__main__` top level | ✗ No | ERROR | True catch-all with `exc_info=True` for full traceback, then `SystemExit(1)`. |

---

## Key Design Decisions

### 1. `fetch_weather` raises, never swallows
Keeping the raw function "pure" (no try/except) means it can be unit-tested in isolation and reused in contexts where the caller wants to handle exceptions differently. Defensive code belongs in the wrapper, not in the core I/O function.

### 2. Retry only on transient errors
Network timeouts and connection drops are transient by nature. HTTP error codes and malformed JSON are *deterministic* — the same request will produce the same broken response. Retrying deterministic failures wastes time and can overload a struggling server. The program retries exactly the transient category.

### 3. Exponential-backoff seed (`RETRY_BACKOFF_SECONDS = 1.5`)
Even a flat 1.5s pause between attempts dramatically reduces thundering-herd effects when many cities fail simultaneously. The config constant makes this tunable without touching logic.

### 4. `None` return instead of exception propagation
`fetch_weather_safe` returns `(None, failure_record)` rather than re-raising. This means `aggregate_weather` can use a simple `if data is not None` branch, keeping the orchestrator linear and readable — no nested try/except soup at the outer layer.

### 5. Structured failure records
Each failure is `{"city": str, "reason": str}` — a named dict rather than a bare string. This makes the `excluded` section of the JSON report machine-readable for downstream dashboards or alerting.

### 6. Three log levels, clearly separated
- **INFO** — a city succeeded or the report was saved. Normal operational signal.
- **WARNING** — a city failed but the program continues. Operator should notice but no action required per individual event.
- **ERROR** — something fatal that will (or should) stop the program. Requires immediate attention.

### 7. `.env` / `config.py` separation
All secrets (future API keys) go in `.env` (git-ignored). All structural configuration (city list, timeouts, URL) goes in `config.py` (committed). Swapping from Open-Meteo to a key-required provider is exactly two changes: set `WEATHER_API_KEY` in `.env` and update `WEATHER_API_BASE_URL`. No logic changes.

### 8. `raise_for_status()` called explicitly
`requests` does not raise on 4xx/5xx by default. Calling `raise_for_status()` inside `fetch_weather` ensures HTTP errors are never silently treated as successful responses with empty bodies.

---

## Test Coverage (7 scenarios, 0 failures)

| # | Scenario | Injection Method | Expected Outcome |
|---|---|---|---|
| 1 | Timeout | `side_effect=requests.Timeout` | `None` + WARNING, retried once |
| 2 | ConnectionError | `side_effect=ConnectionError` | `None` + WARNING, retried once |
| 3 | HTTP 500 | Mock response with `status_code=500` | `None` + WARNING, no retry |
| 4 | Bad JSON | `mock.json.side_effect=ValueError` | `None` + WARNING, no retry |
| 5 | Missing key | Payload `{"forecast": {}}` (no "current") | `None` + WARNING, no retry |
| 6 | Happy path | Full valid mock payload | Weather dict returned, no failure |
| 7 | Mixed aggregate | Cities 1–3 with mixed side effects | 1 success, 2 failures, no crash |

---

## Files Produced

| File | Purpose |
|---|---|
| `weather_aggregator.py` | Core program (fetch, aggregate, save) |
| `config.py` | City list, API URL, timeouts — all tuneable constants |
| `.env` | Secrets placeholder (git-ignored in production) |
| `test_failure_injection.py` | 7-scenario unittest suite with monkey-patching |
| `run_mocked_success.py` | Full mocked success run for demo/CI without network |
| `weather_report.json` | Sample output report |
| `weather_aggregator.log` | Persistent log file written alongside JSON |
