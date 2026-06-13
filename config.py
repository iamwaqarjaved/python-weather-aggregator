"""
config.py — Centralised configuration for Weather Data Aggregator.

City coordinates sourced from WGS-84 reference points (city centres).
All other tuneable knobs (timeout, retry count, output path) live here so
weather_aggregator.py never contains magic numbers.
"""

import os
from dotenv import load_dotenv

load_dotenv()  # Load .env variables before anything else reads os.environ

# ---------------------------------------------------------------------------
# API settings
# ---------------------------------------------------------------------------
WEATHER_API_BASE_URL: str = os.getenv(
    "WEATHER_API_BASE_URL",
    "https://api.open-meteo.com/v1/forecast",
)

# Future key-required providers: set WEATHER_API_KEY in .env
WEATHER_API_KEY: str | None = os.getenv("WEATHER_API_KEY")

# Open-Meteo query parameters that never change between cities
WEATHER_PARAMS_TEMPLATE: dict = {
    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
    "temperature_unit": "celsius",
    "wind_speed_unit": "kmh",
    "timezone": "auto",
}

REQUEST_TIMEOUT_SECONDS: int = 10   # seconds before giving up on a single request
MAX_RETRIES: int = 2                # total attempts per city (1 initial + retries)
RETRY_BACKOFF_SECONDS: float = 1.5  # wait between retries

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
DEFAULT_OUTPUT_PATH: str = "weather_report.json"

# ---------------------------------------------------------------------------
# City list
# ---------------------------------------------------------------------------
# Each entry: {"name": str, "lat": float, "lon": float}
# Latitude/longitude are decimal degrees; negative = S/W.
CITIES: list[dict] = [
    {"name": "Miami, FL",           "lat": 25.7617,   "lon": -80.1918},
    {"name": "New York, NY",        "lat": 40.7128,   "lon": -74.0060},
    {"name": "Los Angeles, CA",     "lat": 34.0522,   "lon": -118.2437},
    {"name": "Chicago, IL",         "lat": 41.8781,   "lon": -87.6298},
    {"name": "London, UK",          "lat": 51.5074,   "lon": -0.1278},
    {"name": "Tokyo, Japan",        "lat": 35.6762,   "lon": 139.6503},
    {"name": "Sydney, Australia",   "lat": -33.8688,  "lon": 151.2093},
    {"name": "Dubai, UAE",          "lat": 25.2048,   "lon": 55.2708},
    # --- Intentionally bad entry for failure testing ---
    {"name": "InvalidCity_BadCoords", "lat": 9999.0,  "lon": 9999.0},
]

# WMO Weather Code descriptions (subset) for human-readable output
WMO_CODES: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm w/ heavy hail",
}
