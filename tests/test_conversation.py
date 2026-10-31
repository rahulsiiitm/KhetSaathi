from fastapi.testclient import TestClient

import app as app_module
from agent import HISTORY_ANSWER_CHARS, build_request

client = TestClient(app_module.app)

BASE = {"question": "And what about tomorrow?", "place": "Ludhiana", "state": "Punjab", "crop": "Potato"}


def test_request_without_history_has_no_earlier_section():
    text = build_request("Should I irrigate?", "Ludhiana", "Punjab", "Potato")
    assert "Earlier in this conversation" not in text
    assert "Farmer's question: Should I irrigate?" in text


def test_request_includes_earlier_turns_before_the_new_question():
    history = [("Should I spray today?", "Decision: Wait, rain is expected.")]
    text = build_request("And tomorrow?", "Ludhiana", "Punjab", "Potato", history)
    assert text.index("Farmer: Should I spray today?") < text.index("Farmer's question: And tomorrow?")
    assert "KhetSaathi: Decision: Wait, rain is expected." in text


def test_long_past_answers_are_trimmed_for_the_model():
    history = [("q", "x" * 5000)]
    text = build_request("next", "Ludhiana", "Punjab", "Potato", history)
    assert "x" * HISTORY_ANSWER_CHARS in text
    assert "x" * (HISTORY_ANSWER_CHARS + 1) not in text


def test_more_than_four_past_turns_is_rejected():
    turn = {"question": "earlier question", "answer": "earlier answer"}
    response = client.post("/advise", json={**BASE, "history": [turn] * 5})
    assert response.status_code == 422


def test_past_answer_over_limit_is_rejected():
    turn = {"question": "earlier question", "answer": "x" * 3001}
    response = client.post("/advise", json={**BASE, "history": [turn]})
    assert response.status_code == 422

