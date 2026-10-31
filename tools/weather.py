"""Live weather for any place in India, from Open-Meteo (no API key needed).

Two calls: a geocoding lookup turns a place name into coordinates,
then the forecast endpoint returns daily rain and temperature for those coordinates.
"""

from datetime import datetime, timezone

import requests

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 15


class WeatherError(Exception):
    """Raised when weather data cannot be fetched. The message is safe to show the user."""


def find_place(name: str) -> dict:
    """Return the best match for a place name inside India."""
    query = name.strip()
    if not query:
        raise WeatherError("Please enter a village, town, or district name.")
    try:
        response = requests.get(
            GEOCODE_URL,
            params={"name": query, "count": 1, "countryCode": "IN", "language": "en"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise WeatherError(f"Place lookup failed: {error}") from error

    results = response.json().get("results") or []
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
    """Return a daily forecast for the place, with the fetch time for citations."""
    place = find_place(name)
    try:
        response = requests.get(
            FORECAST_URL,
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min",
                "forecast_days": days,
                "timezone": "auto",
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise WeatherError(f"Weather service unavailable: {error}") from error

    daily = response.json()["daily"]
    forecast = [
        {
            "date": date,
            "rain_mm": rain,
            "max_c": t_max,
            "min_c": t_min,
        }
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
