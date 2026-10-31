"""Mandi (market) prices from the data.gov.in Agmarknet dataset.

How it works:
1. A sync copies the dataset into the local database (store.mandi_rows). Run it with
   `python -m tools.mandi`. It stops early if the service is down and keeps what it got.
2. Questions are answered from that local copy, so prices show even when the government
   service is slow or down. Each row shows when it was synced, and old data is marked.
3. If a district has nothing locally, the live service is asked once for that district,
   and its rows are saved for next time.

Needs a free data.gov.in API key in .env as DATA_GOV_IN_KEY. Prices are per market, and
a district can have no market at all. That case is reported, not guessed.
"""

import os
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

import store
from tools.cache import SourceDown, cached_fetch

load_dotenv()

API_URL = "https://api.data.gov.in/resource/{resource_id}"
# Agmarknet "Current Daily Price of Various Commodities from Various Markets (Mandi)".
RESOURCE_ID = os.getenv("MANDI_RESOURCE_ID", "9ef84268-d588-465a-a308-a864a43d0070")
TIMEOUT_SECONDS = 8
PAGE_SIZE = 100  # larger pages failed during testing
LIVE_TTL_SECONDS = 6 * 60 * 60
STALE_AFTER_HOURS = 24
SOURCE = "data.gov.in"

# Crops seen in the dataset on 31 Oct 2026. The sync adds every commodity it finds.
SEED_CROPS = [
    "Potato", "Tomato", "Onion", "Cauliflower", "Paddy(Common)", "Paddy(Basmati)", "Wheat",
    "Cabbage", "Brinjal", "Carrot", "Spinach", "Bhindi(Ladies Finger)", "Cucumbar(Kheera)",
    "Bottle gourd", "Pumpkin", "Sponge gourd", "Raddish", "Ginger(Green)", "Coriander(Leaves)",
    "Peas Wet", "Lemon", "Papaya", "Banana", "Apple", "Colacasia",
]


class MandiError(Exception):
    """The request is invalid or the dataset has no answer. Safe to show the user."""


def list_crops() -> list[str]:
    """Every crop we know: the seed list plus every commodity found in the synced data."""
    return sorted(set(SEED_CROPS) | set(store.mandi_commodities()), key=str.lower)


def match_crop(name: str) -> str:
    """Return the dataset's spelling of a crop when it matches ignoring case, else the name as typed."""
    wanted = name.strip().lower()
    for crop in list_crops():
        if crop.lower() == wanted:
            return crop
    return name.strip()


def _request(params: dict) -> dict:
    """Call the API once. Errors never include the URL, so the key cannot leak."""
    try:
        response = requests.get(
            API_URL.format(resource_id=RESOURCE_ID), params=params, timeout=TIMEOUT_SECONDS
        )
    except requests.RequestException as error:
        raise SourceDown(f"Mandi price service unavailable ({type(error).__name__}).") from error
    if response.status_code != 200:
        raise SourceDown(f"Mandi price service unavailable (HTTP {response.status_code}).")
    try:
        body = response.json()
    except ValueError as error:
        raise SourceDown("Mandi price service sent an unreadable answer.") from error
    if "error" in body:
        # The API reports rate limits and bad keys inside a 200 response.
        raise SourceDown(f"Mandi price service refused the request: {body['error']}")
    return body


def _key() -> str:
    return os.getenv("DATA_GOV_IN_KEY", "").strip()


def _normalize(record: dict, state: str = "", district: str = "") -> dict:
    """Turn one API record into the row shape the store uses. Missing values become empty text."""
    def text(value):
        return "" if value is None else str(value)
    return {
        "state": text(record.get("state", state)),
        "district": text(record.get("district", district)),
        "market": text(record.get("market")),
        "commodity": text(record.get("commodity")),
        "variety": text(record.get("variety")),
        "grade": text(record.get("grade")),
        "arrival_date": text(record.get("arrival_date")),
        "min_price": text(record.get("min_price")),
        "max_price": text(record.get("max_price")),
        "modal_price": text(record.get("modal_price")),
    }


def sync_all(max_records: int = 10000) -> int:
    """Copy the dataset into the local store, page by page. Returns how many rows were saved."""
    if not _key():
        raise MandiError("Mandi sync needs DATA_GOV_IN_KEY in .env.")
    saved = 0
    offset = 0
    total = None
    while offset < max_records:
        body = _request({"api-key": _key(), "format": "json", "limit": PAGE_SIZE, "offset": offset})
        if total is None:
            total = int(body.get("total", 0))
        records = body.get("records", [])
        if not records:
            break
        saved += store.save_mandi_rows([_normalize(r) for r in records])
        offset += len(records)
        if offset >= total:
            break
    return saved


def _result(rows: list[dict], state: str, district: str, commodity: str, source: str, stamp: float) -> dict:
    age_hours = round((time.time() - stamp) / 3600, 1)
    return {
        "state": state,
        "district": district,
        "commodity": commodity,
        "rows": [
            {
                "market": row["market"],
                "variety": row["variety"],
                "grade": row["grade"],
                "arrival_date": row["arrival_date"],
                "min_price_per_quintal": row["min_price"],
                "max_price_per_quintal": row["max_price"],
                "modal_price_per_quintal": row["modal_price"],
            }
            for row in rows
        ],
        "source": source,
        "fetched_at": datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds"),
        "age_hours": age_hours,
        "stale": age_hours > STALE_AFTER_HOURS,
    }


def _live_rows(state: str, district: str, commodity: str) -> list[dict]:
    """Ask the live service for one district and save what comes back."""
    if not _key():
        raise MandiError("Mandi prices are unavailable: the data.gov.in key is not set.")
    body = _request({
        "api-key": _key(), "format": "json", "limit": PAGE_SIZE,
        "filters[state.keyword]": state, "filters[district]": district, "filters[commodity]": commodity,
    })
    rows = [_normalize(r, state, district) for r in body.get("records", [])]
    if rows:
        store.save_mandi_rows(rows)
    return rows


def get_mandi_prices(state: str, district: str, commodity: str) -> dict:
    """Latest market prices for a crop in a district: local copy first, then the live service."""
    crop = match_crop(commodity)
    local = store.mandi_rows_for(state, district, crop)
    if local:
        stamp = max(row["synced_at"] for row in local)
        return _result(local, state, district, crop, "data.gov.in (Agmarknet), synced copy", stamp)

    key = f"mandi:{state.lower()}|{district.lower()}|{crop.lower()}"
    live = cached_fetch(
        SOURCE, key, LIVE_TTL_SECONDS,
        lambda: {"rows": _live_rows(state, district, crop), "fetched": time.time()},
    )
    if not live["rows"]:
        raise MandiError(_no_data_message(state, district, crop))
    result = _result(
        live["rows"], state, district, crop, "data.gov.in (Agmarknet), live",
        live.get("fetched", time.time()),
    )
    if live.get("stale"):
        # The live service was down and this is the last saved answer for the district.
        result["stale"] = True
        result["stale_reason"] = live.get("stale_reason", "live service down")
        result["saved_at"] = result["fetched_at"]
    return result


def _no_data_message(state: str, district: str, crop: str) -> str:
    districts = store.mandi_rows_for_state_districts(state)
    if districts:
        sample = ", ".join(districts[:5])
        return (f"No {crop} market prices for {district}, {state} in our data. "
                f"Markets with data in {state} include: {sample}.")
    return f"No {crop} market prices for {district}, {state} in our data."


if __name__ == "__main__":
    try:
        count = sync_all()
        print(f"Synced {count} market rows.")
    except (SourceDown, MandiError) as error:
        print(f"Sync stopped: {error}")
        sys.exit(1)
