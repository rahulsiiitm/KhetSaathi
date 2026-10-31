"""Exact location: turn coordinates into a village and district, and find the nearest markets.

Uses OpenStreetMap's Nominatim service (free, no key). Its usage policy asks for one request
per second and an identifying User-Agent, so lookups are cached for 30 days and paced.
Distances are straight-line ("as the crow flies"), so they are approximate.
"""

import math
import re
import time

import requests

from tools.cache import SourceDown, cached_fetch

NOMINATIM_URL = "https://nominatim.openstreetmap.org"
USER_AGENT = "KhetSaathi-hackathon/1.0 (farm advisory demo)"
TIMEOUT_SECONDS = 8
PLACE_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_MARKETS = 6
_last_call = 0.0

COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


class LocationError(Exception):
    """The location could not be found. Safe to show the user."""


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """Return (lat, lon) if the text is 'lat,lon', otherwise None."""
    match = COORDINATES.match(text or "")
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * radius * math.asin(math.sqrt(a)), 1)


def _pace() -> None:
    """Keep at least one second between Nominatim calls."""
    global _last_call
    wait = 1.1 - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


def _get(path: str, params: dict) -> list | dict:
    _pace()
    try:
        response = requests.get(
            f"{NOMINATIM_URL}/{path}", params={**params, "format": "json"},
            headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as error:
        raise SourceDown(f"Location service unavailable ({type(error).__name__}).") from error


def _clean_district(name: str) -> str:
    return re.sub(r"\s+district$", "", name or "", flags=re.IGNORECASE).strip()


def reverse_geocode(lat: float, lon: float) -> dict:
    """Village or town, district and state for a point. Cached for 30 days by rounded position."""
    key = f"place:{round(lat, 3)},{round(lon, 3)}"

    def lookup() -> dict:
        body = _get("reverse", {"lat": lat, "lon": lon, "zoom": 12, "addressdetails": 1, "accept-language": "en"})
        address = body.get("address") or {}
        village = address.get("village") or address.get("town") or address.get("city") or address.get("suburb") or ""
        district = _clean_district(address.get("state_district") or address.get("county") or "")
        state = address.get("state") or ""
        if not state:
            raise LocationError("We could not find a place name for this location. Enter it by hand.")
        return {"village": village, "district": district, "state": state, "lat": lat, "lon": lon}

    result = cached_fetch("nominatim", key, PLACE_TTL_SECONDS, lookup)
    return {k: result[k] for k in ("village", "district", "state", "lat", "lon")}


def _geocode_market(market: str, district: str, state: str) -> tuple[float, float] | None:
    query = f"{market}, {district}, {state}, India"
    key = f"market-geo:{query.lower()}"

    def lookup() -> dict:
        results = _get("search", {"q": query, "countrycodes": "in", "limit": 1})
        if not results:
            return {"found": False}
        return {"found": True, "lat": float(results[0]["lat"]), "lon": float(results[0]["lon"])}

    found = cached_fetch("nominatim", key, PLACE_TTL_SECONDS, lookup)
    if not found.get("found"):
        return None
    return found["lat"], found["lon"]


def nearest_markets(lat: float, lon: float, state: str, district: str, crop_rows: list[dict]) -> list[dict]:
    """The closest markets that have a price for this crop, with the price and approximate distance.

    crop_rows are the market rows for the crop in the district. Markets that cannot be located
    are left out rather than guessed.
    """
    seen = {}
    for row in crop_rows:
        seen.setdefault(row["market"], row)
    results = []
    for market, row in list(seen.items())[:MAX_MARKETS]:
        try:
            point = _geocode_market(market, district, state)
        except SourceDown:
            break
        if point is None:
            continue
        results.append({
            "market": market,
            "distance_km": distance_km(lat, lon, point[0], point[1]),
            "modal_price_per_quintal": row["modal_price"],
            "arrival_date": row["arrival_date"],
        })
    return sorted(results, key=lambda r: r["distance_km"])
