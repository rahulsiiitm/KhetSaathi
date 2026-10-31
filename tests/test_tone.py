from agent import SYSTEM_PROMPT
from safety import remove_filler


def test_stock_ai_openers_are_removed():
    text = "Certainly! Irrigate your potato today."
    assert remove_filler(text) == "Irrigate your potato today."


def test_ai_self_references_are_removed():
    text = "Decision: Irrigate today. As an AI, I cannot see your field. I hope this helps!"
    cleaned = remove_filler(text)
    assert "As an AI" not in cleaned
    assert "I hope this helps" not in cleaned
    assert cleaned.startswith("Decision: Irrigate today.")


def test_report_phrasing_is_removed_but_the_fact_stays():
    text = "Based on the data, rain is not expected on Friday."
    assert remove_filler(text) == "Rain is not expected on Friday."


def test_rule_codes_are_removed_from_the_farmers_text():
    text = "The field is fine for work (R4). Rain is not expected."
    assert remove_filler(text) == "The field is fine for work. Rain is not expected."


def test_plain_farmer_language_is_untouched():
    text = "Aaj sinchai kar dijiye, agle teen din baarish nahi hai."
    assert remove_filler(text) == text


def test_prompt_asks_for_a_personal_advisor_voice():
    assert "neighbour" in SYSTEM_PROMPT
    assert "Open with the answer" in SYSTEM_PROMPT
    assert "Do not say you are an AI" in SYSTEM_PROMPT
    # The labels the page relies on to lay out the answer must still be in the prompt.
    for label in ["Decision:", "Day-by-day plan:", "Based on:", "Not known:"]:
        assert label in SYSTEM_PROMPT
