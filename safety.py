"""Guardrails applied to every answer before it reaches the farmer.

Rules live in code, not only in the prompt:
1. Chemical dosage lines (for example "2 ml per litre") are removed.
2. Every answer ends with the sources and fetch times of the data it used.
"""

import re

DOSE_PATTERN = re.compile(
    r"\b\d+(\.\d+)?\s*(ml|mL|g|gm|gram|kg|kilogram|l|litre|liter)\s*"
    r"(/|per)\s*(acre|ha|hectare|bigha|litre|liter|kg|kilogram|tank|l)\b",
    re.IGNORECASE,
)
DOSE_REPLACEMENT = (
    "[Dosage removed: ask your local Krishi Vigyan Kendra or agriculture officer "
    "for the correct chemical dose.]"
)


def remove_dosages(text: str) -> tuple[str, bool]:
    """Replace any line that contains a chemical dose. Return the text and whether anything changed."""
    cleaned_lines = []
    changed = False
    for line in text.splitlines():
        if DOSE_PATTERN.search(line):
            cleaned_lines.append(DOSE_REPLACEMENT)
            changed = True
        else:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines), changed


def source_lines(trace: list[dict]) -> list[str]:
    """Build the source list from tool results that succeeded, not from the model's text."""
    lines = []
    for step in trace:
        result = step["result"]
        if "error" in result:
            continue
        if step["tool"] == "get_weather":
            place = result["place"]
            lines.append(
                f"Weather: {result['source']} forecast for {place['name']}, {place['state']} "
                f"(fetched {result['fetched_at']})"
            )
        elif step["tool"] == "get_mandi_prices":
            lines.append(
                f"Mandi prices: {result['source']} for {result['commodity']} in "
                f"{result['district']}, {result['state']} (fetched {result['fetched_at']})"
            )
    return lines


def check_answer(text: str, trace: list[dict]) -> dict:
    """Apply all guardrails and return the final answer with its warnings."""
    cleaned, dosage_removed = remove_dosages(text.strip())
    warnings = []
    if dosage_removed:
        warnings.append("A chemical dosage line was removed from the answer.")

    failed = [step["tool"] for step in trace if "error" in step["result"]]
    for tool in failed:
        warnings.append(f"{tool} failed, so its data is not in this answer.")

    sources = source_lines(trace)
    if sources:
        cleaned += "\n\nSources:\n" + "\n".join(f"- {line}" for line in sources)
    else:
        warnings.append("No live data could be fetched, so this answer is general guidance only.")

    return {"advice": cleaned, "sources": sources, "warnings": warnings}
