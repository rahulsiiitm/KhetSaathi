"""Live weather for any place in India, from Open-Meteo (no API key needed).

Two calls: a geocoding lookup turns a place name into coordinates,
then the forecast endpoint returns daily rain and temperature for those coordinates.
Forecasts are cached for 30 minutes; place lookups are cached for 30 days.
"""

from datetime import datetime, timezone

import requests

from tools.cache import SourceDown, cached_fetch
from tools.places import parse_coordinates

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 10
FORECAST_TTL_SECONDS = 30 * 60
PLACE_TTL_SECONDS = 30 * 24 * 60 * 60
SOURCE = "open-meteo"


class WeatherError(Exception):
    """The request itself is invalid, e.g. an empty or unknown place name. Safe to show the user."""


def _get_json(url: str, params: dict) -> dict:
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as error:
        raise SourceDown(f"Weather service unavailable ({type(error).__name__}).") from error


def find_place(name: str) -> dict:
    """Return the best match for a place name inside India, or the exact point for 'lat,lon'."""
    coordinates = parse_coordinates(name)
    if coordinates:
        lat, lon = coordinates
        return {"name": f"{lat:.4f}, {lon:.4f}", "state": "", "latitude": lat, "longitude": lon}
    query = name.strip()
    if not query:
        raise WeatherError("Please enter a village, town, or district name.")
    return cached_fetch(
        f"{SOURCE}-geocode",
        f"place:{query.lower()}",
        PLACE_TTL_SECONDS,
        lambda: _lookup_place(query),
    )


def _lookup_place(query: str) -> dict:
    results = _get_json(
        GEOCODE_URL,
        {"name": query, "count": 1, "countryCode": "IN", "language": "en"},
    ).get("results") or []
    if not results:
        raise WeatherError(f"No Indian place found matching '{query}'.")
    place = results[0]
    return {
        "name": place["name"],
        "state": place.get("admin1", ""),
        "latitude": place["latitude"],
        "longitude": place["longitude"],
    }


def get_weather(name: str, days: int = 3) -> dict:
    """Return a daily forecast for the place, with cache status and fetch time for citations."""
    place = find_place(name)
    return cached_fetch(
        SOURCE,
        f"forecast:{place['latitude']:.3f},{place['longitude']:.3f}:{days}",
        FORECAST_TTL_SECONDS,
        lambda: _lookup_forecast(place, days),
    )


def _lookup_forecast(place: dict, days: int) -> dict:
    daily = _get_json(
        FORECAST_URL,
        {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min",
            "forecast_days": days,
            "timezone": "auto",
        },
    )["daily"]
    forecast = [
        {"date": date, "rain_mm": rain, "max_c": t_max, "min_c": t_min}
        for date, rain, t_max, t_min in zip(
            daily["time"],
            daily["precipitation_sum"],
            daily["temperature_2m_max"],
            daily["temperature_2m_min"],
        )
    ]
    return {
        "place": place,
        "forecast": forecast,
        "source": "Open-Meteo",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
