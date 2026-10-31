"""One place that decides how every live data call is served.

Order of checks for a request:
1. Fresh cache entry -> return it (cache = "hit").
2. Source paused by the circuit breaker -> return the last saved result marked stale,
   or fail fast with a clear message if nothing was ever saved.
3. Live fetch -> on success, save to cache and clear the failure count (cache = "miss").
4. Live fetch fails with an outage -> record the failure, then return the last saved
   result marked stale, or raise SourceDown if there is none.

Only outages (SourceDown) count against the circuit breaker. "No data for this district"
is a real answer, not an outage, so it is never retried or cached as a failure.
"""

import time
from datetime import datetime, timezone

import store


class SourceDown(RuntimeError):
    """An upstream service is unreachable or erroring. The message is safe to show the user."""


def _stale(payload: dict, stored_at: float, reason: str) -> dict:
    age_minutes = int((time.time() - stored_at) // 60)
    return {
        **payload,
        "cache": "stale",
        "stale": True,
        "stale_reason": reason,
        "saved_at": datetime.fromtimestamp(stored_at, timezone.utc).isoformat(timespec="seconds"),
        "saved_minutes_ago": age_minutes,
    }


def cached_fetch(source: str, key: str, ttl_seconds: int, fetch) -> dict:
    """Serve one data request through the cache, the circuit breaker, and the live fetch."""
    saved = store.cache_get(key)
    if saved is not None and saved[2]:
        return {**saved[0], "cache": "hit", "stale": False}

    if store.breaker_open(source):
        if saved is not None:
            return _stale(saved[0], saved[1], f"{source} is paused after repeated failures")
        raise SourceDown(f"{source} is paused after repeated failures. Try again in a few minutes.")

    try:
        live = fetch()
    except SourceDown as error:
        store.record_failure(source, str(error))
        if saved is not None:
            return _stale(saved[0], saved[1], str(error))
        raise

    store.record_success(source)
    store.cache_put(key, live, ttl_seconds)
    return {**live, "cache": "miss", "stale": False}
