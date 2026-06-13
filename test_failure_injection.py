"""
test_failure_injection.py
=========================
Deliberately exercises every error path in weather_aggregator.py using
monkey-patching so no real network calls are made.

Test scenarios
--------------
1. Timeout          — requests.get raises Timeout
2. ConnectionError  — requests.get raises ConnectionError
3. HTTP 500         — server returns a 500 response
4. Bad JSON         — response body is not valid JSON
5. Missing key      — response JSON lacks the 'current' key
6. Happy path       — fully mocked successful response
7. Full aggregate   — mix of good + broken cities via aggregate_weather()
"""

import json
import logging
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure the project root is on sys.path when run from any directory.
sys.path.insert(0, ".")

import requests

import weather_aggregator as wa
import config

# Use the module's own logger so output matches production format.
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code: int = 200, json_data: dict | None = None,
                   text: str = "", raise_json: bool = False) -> MagicMock:
    """Build a fake requests.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text or json.dumps(json_data or {})

    if raise_json:
        mock.json.side_effect = ValueError("No JSON object could be decoded")
    else:
        mock.json.return_value = json_data or {}

    # raise_for_status mimics real behaviour
    if status_code >= 400:
        mock.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Error", response=mock
        )
    else:
        mock.raise_for_status.return_value = None

    return mock


GOOD_PAYLOAD = {
    "current": {
        "time":               "2025-06-13T14:00",
        "temperature_2m":     28.5,
        "relative_humidity_2m": 72,
        "wind_speed_10m":     15.3,
        "weather_code":       2,
    }
}

GOOD_CITY = {"name": "TestCity", "lat": 25.76, "lon": -80.19}


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestFailureInjection(unittest.TestCase):

    # ── 1. Timeout ──────────────────────────────────────────────────────────
    @patch("requests.get", side_effect=requests.exceptions.Timeout)
    def test_timeout_returns_none(self, _mock):
        logger.info("[TEST] Scenario 1 — Timeout")
        data, failure = wa.fetch_weather_safe(GOOD_CITY)
        self.assertIsNone(data)
        self.assertIn("Network failure", failure["reason"])
        logger.info("       PASS — failure reason: %s", failure["reason"])

    # ── 2. ConnectionError ──────────────────────────────────────────────────
    @patch("requests.get",
           side_effect=requests.exceptions.ConnectionError("DNS resolution failed"))
    def test_connection_error_returns_none(self, _mock):
        logger.info("[TEST] Scenario 2 — ConnectionError")
        data, failure = wa.fetch_weather_safe(GOOD_CITY)
        self.assertIsNone(data)
        self.assertIn("Network failure", failure["reason"])
        logger.info("       PASS — failure reason: %s", failure["reason"])

    # ── 3. HTTP 500 ─────────────────────────────────────────────────────────
    @patch("requests.get",
           return_value=_mock_response(500, text="Internal Server Error"))
    def test_http_500_returns_none(self, _mock):
        logger.info("[TEST] Scenario 3 — HTTP 500")
        data, failure = wa.fetch_weather_safe(GOOD_CITY)
        self.assertIsNone(data)
        self.assertIn("Invalid response", failure["reason"])
        logger.info("       PASS — failure reason: %s", failure["reason"])

    # ── 4. Bad JSON ─────────────────────────────────────────────────────────
    @patch("requests.get",
           return_value=_mock_response(200, raise_json=True))
    def test_bad_json_returns_none(self, _mock):
        logger.info("[TEST] Scenario 4 — Bad JSON body")
        data, failure = wa.fetch_weather_safe(GOOD_CITY)
        self.assertIsNone(data)
        self.assertIn("Invalid response", failure["reason"])
        logger.info("       PASS — failure reason: %s", failure["reason"])

    # ── 5. Missing key ──────────────────────────────────────────────────────
    @patch("requests.get",
           return_value=_mock_response(200, json_data={"forecast": {}}))
    def test_missing_key_returns_none(self, _mock):
        logger.info("[TEST] Scenario 5 — Missing 'current' key in response")
        data, failure = wa.fetch_weather_safe(GOOD_CITY)
        self.assertIsNone(data)
        self.assertIn("Missing API field", failure["reason"])
        logger.info("       PASS — failure reason: %s", failure["reason"])

    # ── 6. Happy path ───────────────────────────────────────────────────────
    @patch("requests.get",
           return_value=_mock_response(200, json_data=GOOD_PAYLOAD))
    def test_happy_path(self, _mock):
        logger.info("[TEST] Scenario 6 — Happy path (mocked success)")
        data, failure = wa.fetch_weather_safe(GOOD_CITY)
        self.assertIsNotNone(data)
        self.assertIsNone(failure)
        self.assertEqual(data["current"]["temperature_2m"], 28.5)
        logger.info("       PASS — temperature returned: %.1f°C",
                    data["current"]["temperature_2m"])

    # ── 7. Aggregate with mixed cities ──────────────────────────────────────
    def test_aggregate_mixed(self):
        logger.info("[TEST] Scenario 7 — aggregate_weather() with mixed results")

        cities = [
            {"name": "GoodCity",     "lat": 25.76,  "lon": -80.19},
            {"name": "TimeoutCity",  "lat": 0.0,    "lon": 0.0},
            {"name": "BadJSONCity",  "lat": 1.0,    "lon": 1.0},
        ]

        responses_iter = iter([
            _mock_response(200, json_data=GOOD_PAYLOAD),       # GoodCity
            requests.exceptions.Timeout,                        # TimeoutCity (all retries)
            requests.exceptions.Timeout,                        # TimeoutCity retry
            _mock_response(200, raise_json=True),              # BadJSONCity
        ])

        def side_effect_factory(*args, **kwargs):
            val = next(responses_iter)
            if isinstance(val, type) and issubclass(val, Exception):
                raise val()
            if isinstance(val, Exception):
                raise val
            return val

        with patch("requests.get", side_effect=side_effect_factory):
            successes, failures = wa.aggregate_weather(cities)

        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures),  2)
        self.assertEqual(successes[0]["city"], "GoodCity")
        failed_names = {f["city"] for f in failures}
        self.assertIn("TimeoutCity", failed_names)
        self.assertIn("BadJSONCity", failed_names)
        logger.info("       PASS — 1 success, 2 failures as expected")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "═" * 60)
    print("  FAILURE INJECTION TEST SUITE")
    print("═" * 60 + "\n")
    unittest.main(verbosity=2)
