from fastapi.testclient import TestClient

import app as app_module
import store

client = TestClient(app_module.app)


def test_status_reports_sources_cache_and_answers():
    store.record_failure("data.gov.in", "HTTP 502")
    store.cache_put("k", {"v": 1}, ttl_seconds=60)
    store.log_advice("Ludhiana", "Potato", "q", "a", [], ["get_weather"], 900)

    body = client.get("/status").json()

    source = next(s for s in body["sources"] if s["source"] == "data.gov.in")
    assert source["consecutive_failures"] == 1
    assert source["paused"] is False
    assert body["cache"]["fresh_entries"] == 1
    assert body["answers"]["answers_served"] == 1
