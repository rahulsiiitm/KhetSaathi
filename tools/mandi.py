"""Latest mandi (market) prices from the data.gov.in Agmarknet dataset.

Needs a free data.gov.in API key in .env as DATA_GOV_IN_KEY.
Prices are per market, so a district can have no data. That case is reported, not guessed.
The upstream service is intermittently unavailable, so requests are retried a few times.
"""

import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.data.gov.in/resource/{resource_id}"
# Agmarknet "Current Daily Price of Various Commodities from Various Markets (Mandi)".
RESOURCE_ID = os.getenv("MANDI_RESOURCE_ID", "9ef84268-d588-465a-a308-a864a43d0070")
TIMEOUT_SECONDS = 25
ATTEMPTS = 3
PAGE_SIZE = 100  # larger pages failed during testing

# Commodity names must match the dataset exactly.
SUPPORTED_CROPS = ["Potato", "Tomato", "Onion", "Cauliflower", "Paddy(Common)"]


class MandiError(Exception):
    """Raised when mandi prices cannot be fetched. The message is safe to show the user."""


def _request(params: dict) -> dict:
    """Call the API with retries. Errors never include the URL, so the key cannot leak."""
    last_problem = "unknown error"
    for attempt in range(ATTEMPTS):
        try:
            response = requests.get(
                API_URL.format(resource_id=RESOURCE_ID), params=params, timeout=TIMEOUT_SECONDS
            )
            if response.status_code == 200:
                body = response.json()
                if "error" in body:
                    # The API reports rate limits and bad keys inside a 200 response.
                    raise MandiError(f"Mandi price service refused the request: {body['error']}")
                return body
            last_problem = f"HTTP {response.status_code}"
        except requests.RequestException as error:
            last_problem = type(error).__name__
        except ValueError:
            last_problem = "invalid response"
        time.sleep(1.5 * (attempt + 1))
    raise MandiError(f"Mandi price service unavailable ({last_problem}). Try again later.")


def get_mandi_prices(state: str, district: str, commodity: str, limit: int = 20) -> dict:
    """Return the latest market rows for a commodity in a district."""
    api_key = os.getenv("DATA_GOV_IN_KEY", "").strip()
    if not api_key:
        raise MandiError("Mandi prices are unavailable: the data.gov.in key is not set.")
    if commodity not in SUPPORTED_CROPS:
        raise MandiError(f"'{commodity}' is not a supported crop for mandi prices.")

    body = _request(
        {
            "api-key": api_key,
            "format": "json",
            "limit": min(limit, PAGE_SIZE),
            "filters[state.keyword]": state,
            "filters[district]": district,
            "filters[commodity]": commodity,
        }
    )

    rows = [
        {
            "market": row.get("market"),
            "commodity": row.get("commodity"),
            "variety": row.get("variety"),
            "arrival_date": row.get("arrival_date"),
            "min_price_per_quintal": row.get("min_price"),
            "max_price_per_quintal": row.get("max_price"),
            "modal_price_per_quintal": row.get("modal_price"),
        }
        for row in body.get("records", [])
    ]
    if not rows:
        raise MandiError(
            f"No {commodity} market prices found for {district}, {state} in today's dataset."
        )

    return {
        "state": state,
        "district": district,
        "commodity": commodity,
        "rows": rows,
        "source": "data.gov.in (Agmarknet)",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
