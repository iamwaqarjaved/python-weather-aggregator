"""
weather_aggregator.py
=====================
Module 4 — Lab 4: Weather Data Aggregator

Pulls current weather for a configurable list of cities from Open-Meteo
(free, no API key required), handles every realistic failure mode, and
writes a structured JSON report.

Design principles
-----------------
* fetch_weather()       — pure network I/O; raises on any problem, never swallows errors.
* fetch_weather_safe()  — wraps fetch_weather; catches all expected exceptions and returns
                          None + a structured failure record instead of crashing.
* aggregate_weather()   — orchestrates all cities; never crashes regardless of individual failures.
* save_report()         — writes final JSON with timestamp, successes, and excluded list.
* Logging               — INFO for successes, WARNING for individual failures, ERROR for fatal.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Tuple   # add Tuple here if not present

import requests

import config

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),                          # Console
        logging.FileHandler("weather_aggregator.log"),   # Persistent file
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core fetch — raises on any failure
# ---------------------------------------------------------------------------

def fetch_weather(lat: float, lon: float) -> dict:
    """
    Fetch current weather from Open-Meteo for a single (lat, lon) pair.

    Returns the parsed JSON dict on success.

    Raises
    ------
    requests.RequestException
        Any network-layer problem: DNS failure, timeout, connection refused, etc.
    ValueError
        HTTP 4xx/5xx response, or the response body is not valid JSON.
    KeyError
        Response JSON is missing the expected 'current' key (API contract broken).
    """
    params = dict(config.WEATHER_PARAMS_TEMPLATE)  # shallow copy — never mutate the template
    params["latitude"] = lat
    params["longitude"] = lon

    # One-line swap point: if WEATHER_API_KEY is set, attach it as a header or param here.
    headers = {}
    if config.WEATHER_API_KEY:
        headers["Authorization"] = f"Bearer {config.WEATHER_API_KEY}"

    response = requests.get(
        config.WEATHER_API_BASE_URL,
        params=params,
        headers=headers,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )

    # Raise HTTPError for 4xx / 5xx — not automatically raised by requests.
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise ValueError(f"HTTP {response.status_code}: {response.text[:200]}") from exc

    # Parse body — raises ValueError if not valid JSON.
    data = response.json()

    # Validate schema — raises KeyError if API contract changes.
    _ = data["current"]        # must exist
    _ = data["current"]["temperature_2m"]  # must exist

    return data


# ---------------------------------------------------------------------------
# Safe wrapper — returns None + failure record on any error
# ---------------------------------------------------------------------------
def fetch_weather_safe(city: dict) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Wraps fetch_weather with full error handling.

    Parameters
    ----------
    city : dict
        Must contain keys 'name', 'lat', 'lon'.

    Returns
    -------
    (weather_data, None)      on success
    (None, failure_record)    on any failure

    Never raises.
    """
    name = city["name"]
    lat  = city["lat"]
    lon  = city["lon"]

    last_exception: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            data = fetch_weather(lat, lon)
            if attempt > 1:
                logger.info("✓ %s — succeeded on attempt %d", name, attempt)
            else:
                logger.info("✓ %s — OK (%.1f°C, %s)",
                            name,
                            data["current"]["temperature_2m"],
                            config.WMO_CODES.get(data["current"].get("weather_code", -1), "Unknown"))
            return data, None

        except requests.exceptions.Timeout:
            last_exception = Exception(f"Timed out after {config.REQUEST_TIMEOUT_SECONDS}s")
            logger.warning("⚠ %s — attempt %d/%d timed out; retrying…",
                           name, attempt, config.MAX_RETRIES)

        except requests.RequestException as exc:
            last_exception = exc
            logger.warning("⚠ %s — attempt %d/%d network error: %s",
                           name, attempt, config.MAX_RETRIES, exc)

        except ValueError as exc:
            # HTTP error or bad JSON — retrying won't help; fail fast.
            logger.warning("✗ %s — invalid response (no retry): %s", name, exc)
            return None, {"city": name, "reason": f"Invalid response: {exc}"}

        except KeyError as exc:
            # API schema changed — retrying won't help; fail fast.
            logger.warning("✗ %s — unexpected API schema, missing key %s", name, exc)
            return None, {"city": name, "reason": f"Missing API field: {exc}"}

        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF_SECONDS)

    # All retries exhausted for network/timeout errors.
    reason = f"Network failure after {config.MAX_RETRIES} attempts: {last_exception}"
    logger.warning("✗ %s — %s", name, reason)
    return None, {"city": name, "reason": reason}


# ---------------------------------------------------------------------------
# Aggregator — fetches all cities, never crashes
# ---------------------------------------------------------------------------
def aggregate_weather(cities: list[dict]) -> Tuple[list, list]:
    """
    Fetch weather for every city in the list.

    Parameters
    ----------
    cities : list[dict]
        Each dict must have 'name', 'lat', 'lon'.

    Returns
    -------
    (successes, failures)
    successes : list of dicts  — enriched weather records
    failures  : list of dicts  — {city, reason} pairs
    """
    logger.info("═" * 60)
    logger.info("Starting aggregation for %d cities", len(cities))
    logger.info("═" * 60)

    successes: list[dict] = []
    failures:  list[dict] = []

    for city in cities:
        data, failure = fetch_weather_safe(city)

        if data is not None:
            current = data["current"]
            code    = current.get("weather_code", -1)
            record  = {
                "city":              city["name"],
                "latitude":          city["lat"],
                "longitude":         city["lon"],
                "temperature_c":     current.get("temperature_2m"),
                "humidity_pct":      current.get("relative_humidity_2m"),
                "wind_speed_kmh":    current.get("wind_speed_10m"),
                "weather_code":      code,
                "weather_desc":      config.WMO_CODES.get(code, "Unknown"),
                "observation_time":  current.get("time"),
            }
            successes.append(record)
        else:
            failures.append(failure)

    logger.info("═" * 60)
    logger.info("Aggregation complete: %d succeeded, %d failed",
                len(successes), len(failures))
    logger.info("═" * 60)

    return successes, failures


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

def save_report(successes: list[dict], failures: list[dict],
                output_path: str = config.DEFAULT_OUTPUT_PATH) -> None:
    """
    Write a structured JSON report to disk.

    Report schema
    -------------
    {
      "generated_at": "<ISO-8601 UTC timestamp>",
      "summary": { "total": int, "succeeded": int, "failed": int },
      "weather_data": [ ... ],
      "excluded": [ {"city": str, "reason": str}, ... ]
    }
    """
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total":     len(successes) + len(failures),
            "succeeded": len(successes),
            "failed":    len(failures),
        },
        "weather_data": successes,
        "excluded": failures,
    }

    try:
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        logger.info("Report saved → %s", output_path)
    except OSError as exc:
        logger.error("FATAL: could not write report to %s — %s", output_path, exc)
        raise  # re-raise so the caller can decide how to handle it


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        successes, failures = aggregate_weather(config.CITIES)
        save_report(successes, failures)
    except Exception as exc:  # noqa: BLE001 — true catch-all only at top level
        logger.error("FATAL unhandled exception: %s", exc, exc_info=True)
        raise SystemExit(1) from exc
