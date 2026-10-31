import pytest

import store
from tools.cache import SourceDown, cached_fetch


def test_cache_fresh_entry_is_returned():
    store.cache_put("k", {"v": 1}, ttl_seconds=60)
    payload, _stored_at, fresh = store.cache_get("k")
    assert payload == {"v": 1}
    assert fresh is True


def test_cache_expired_entry_is_marked_not_fresh():
    store.cache_put("k", {"v": 1}, ttl_seconds=0)
    _payload, _stored_at, fresh = store.cache_get("k")
    assert fresh is False


def test_cache_miss_returns_none():
    assert store.cache_get("never-stored") is None


def test_breaker_opens_after_repeated_failures():
    for _ in range(store.BREAKER_FAILURES - 1):
        store.record_failure("src", "down")
    assert store.breaker_open("src") is False
    store.record_failure("src", "down")
    assert store.breaker_open("src") is True


def test_success_resets_failures_and_closes_breaker():
    for _ in range(store.BREAKER_FAILURES):
        store.record_failure("src", "down")
    store.record_success("src")
    assert store.breaker_open("src") is False
    assert store.health_snapshot()[0]["consecutive_failures"] == 0


def test_cached_fetch_serves_hit_without_calling_source():
    calls = []
    fetch = lambda: calls.append(1) or {"v": 1}
    first = cached_fetch("src", "key", 60, fetch)
    second = cached_fetch("src", "key", 60, fetch)
    assert first["cache"] == "miss"
    assert second["cache"] == "hit"
    assert len(calls) == 1


def test_cached_fetch_falls_back_to_stale_on_outage():
    store.cache_put("key", {"v": 7}, ttl_seconds=0)  # saved but already expired

    def down():
        raise SourceDown("service down")

    result = cached_fetch("src", "key", 60, down)
    assert result["stale"] is True
    assert result["v"] == 7
    assert "service down" in result["stale_reason"]


def test_cached_fetch_raises_when_no_saved_result_and_source_down():
    def down():
        raise SourceDown("service down")

    with pytest.raises(SourceDown):
        cached_fetch("src", "key", 60, down)


def test_open_breaker_skips_the_network_entirely():
    for _ in range(store.BREAKER_FAILURES):
        store.record_failure("src", "down")
    calls = []
    with pytest.raises(SourceDown, match="paused"):
        cached_fetch("src", "key", 60, lambda: calls.append(1))
    assert calls == []


def test_advice_stats_counts_logged_answers():
    store.log_advice("Ludhiana", "Potato", "q", "a", [], ["get_weather"], 1200)
    store.log_advice("Ludhiana", "Potato", "q2", "a2", [], ["get_weather"], 800)
    stats = store.advice_stats()
    assert stats["answers_served"] == 2
    assert stats["average_latency_ms"] == 1000
