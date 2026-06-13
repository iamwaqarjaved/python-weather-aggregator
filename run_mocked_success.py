"""
run_mocked_success.py
=====================
Simulates a fully successful production run by monkey-patching requests.get
with realistic Open-Meteo payloads for every city in config.CITIES.

Run this to see the INFO-level logger output and generate a realistic
weather_report.json without needing real network access.
"""
import sys, json
from unittest.mock import MagicMock, patch
sys.path.insert(0, ".")

import config
import weather_aggregator as wa

# ---------------------------------------------------------------------------
# Build one realistic payload per city
# ---------------------------------------------------------------------------
CITY_DATA = {
    "Miami, FL":            (31.2, 82, 18.0, 80),   # temp, humidity, wind, wmo
    "New York, NY":         (22.5, 65, 24.0, 2),
    "Los Angeles, CA":      (26.8, 55, 10.5, 0),
    "Chicago, IL":          (19.3, 70, 32.0, 3),
    "London, UK":           (15.1, 78, 20.0, 61),
    "Tokyo, Japan":         (28.7, 75, 15.0, 51),
    "Sydney, Australia":    (13.4, 60, 22.0, 2),
    "Dubai, UAE":           (38.9, 45,  8.0, 0),
    "InvalidCity_BadCoords": None,   # will raise to trigger failure path
}

call_index = [0]

def mock_get(*args, **kwargs):
    params = kwargs.get("params", {})
    # Match city by coordinates
    lat = float(params.get("latitude", 0))
    lon = float(params.get("longitude", 0))

    # Find matching city
    matched = None
    for city in config.CITIES:
        if abs(city["lat"] - lat) < 0.01 and abs(city["lon"] - lon) < 0.01:
            matched = city["name"]
            break

    resp = MagicMock()

    if matched is None or CITY_DATA.get(matched) is None:
        # Simulate API rejecting bad coordinates
        resp.status_code = 400
        resp.text = "Bad coordinates"
        resp.raise_for_status.side_effect = __import__("requests").HTTPError(
            "400", response=resp)
        return resp

    temp, hum, wind, wmo = CITY_DATA[matched]
    payload = {
        "current": {
            "time": "2026-06-13T20:00",
            "temperature_2m": temp,
            "relative_humidity_2m": hum,
            "wind_speed_10m": wind,
            "weather_code": wmo,
        }
    }
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    resp.text = json.dumps(payload)
    return resp

if __name__ == "__main__":
    print("\n" + "═"*60)
    print("  MOCKED SUCCESS RUN — simulates live API responses")
    print("═"*60 + "\n")

    with patch("requests.get", side_effect=mock_get):
        successes, failures = wa.aggregate_weather(config.CITIES)
        wa.save_report(successes, failures, "weather_report.json")

    print(f"\n✓ Report written. {len(successes)} cities succeeded, {len(failures)} failed.")
