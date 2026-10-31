"""Guardrails applied to every answer before it reaches the farmer.

Rules live in code, not only in the prompt:
1. Chemical dosage lines (for example "2 ml per litre") are removed.
2. Every number with a unit (mm, °C, ₹, per quintal) must match a value a tool returned.
   Numbers that do not match are flagged to the farmer.
3. Stale mandi prices (from an earlier fetch) are labeled as stale.
4. Every answer ends with the sources and fetch times of the data it used.
"""

import json
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
# A number followed by a unit that the tools report (weather in mm or °C, prices in ₹ or per quintal).
FIGURE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:mm|°\s*C|℃|₹|rs\.?|rupees|per\s+quintal|/\s*quintal|quintal)",
    re.IGNORECASE,
)
NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")
TOLERANCE = 0.05


TOOL_LABELS = {
    "get_weather": "Weather forecast",
    "assess_field_risk": "Field-risk check",
    "get_mandi_prices": "Mandi prices",
}


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


def unmatched_figures(text: str, trace: list[dict]) -> list[str]:
    """Return figures with units in the answer that no successful tool result contains."""
    tool_numbers = []
    for step in trace:
        if "error" not in step["result"]:
            tool_numbers += [float(n) for n in NUMBER_PATTERN.findall(json.dumps(step["result"]))]

    missing = []
    for match in FIGURE_PATTERN.finditer(text):
        value = float(match.group(1))
        if not any(abs(value - known) <= TOLERANCE for known in tool_numbers):
            missing.append(match.group(0))
    return missing


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
                f"(fetched {result['fetched_at']}){_freshness(result)}"
            )
        elif step["tool"] == "assess_field_risk":
            place = result["place"]
            lines.append(
                f"Field risks: {result['source']} for {place['name']}, {place['state']} "
                f"(rules {result['rules']}; fetched {result['fetched_at']}){_freshness(result)}"
            )
        elif step["tool"] == "get_mandi_prices":
            lines.append(
                f"Mandi prices: {result['source']} for {result['commodity']} in "
                f"{result['district']}, {result['state']} (fetched {result['fetched_at']})"
                f"{_freshness(result)}"
            )
    return lines


def _freshness(result: dict) -> str:
    """Label cached or stale data so the farmer knows how old it is."""
    if result.get("stale"):
        return f" - STALE: {result.get('stale_reason', 'live service down')}; last saved {result.get('saved_at')}"
    if result.get("cache") == "hit":
        return " - served from cache"
    return ""


FILLER = [
    re.compile(r"\b(?:As an AI|as an AI language model)\b[^.]*\.\s*", re.IGNORECASE),
    re.compile(r"\bI hope this helps[^.!]*[.!]\s*", re.IGNORECASE),
    re.compile(r"\b(?:Certainly|Of course|Great question)\b[,!.]?\s*", re.IGNORECASE),
    re.compile(r"\b(?:Based on|According to) (?:the |this |my )?(?:data|tools?|information|results?|analysis)\b[^,.:]*[,:]\s*", re.IGNORECASE),
    re.compile(r"\b(?:The data shows|The tool (?:returned|shows))\b[^,.]*[,.]\s*", re.IGNORECASE),
    # Rule codes belong in the sources list, not in what the farmer reads.
    re.compile(r"\s*\(R[1-5]\)"),
]


def remove_filler(text: str) -> str:
    """Take out stock phrases that make an answer sound like a generated report."""
    for pattern in FILLER:
        text = pattern.sub("", text)
    # Keep the first letter of each label line capitalised after a phrase was removed.
    return "\n".join(line[:1].upper() + line[1:] if line else line for line in text.split("\n"))


def check_answer(text: str, trace: list[dict]) -> dict:
    """Apply all guardrails and return the final answer with its warnings."""
    cleaned, dosage_removed = remove_dosages(remove_filler(text.strip()))
    warnings = []
    if dosage_removed:
        warnings.append("A chemical dosage line was removed from the answer.")

    for step in trace:
        label = TOOL_LABELS.get(step["tool"], step["tool"])
        if "error" in step["result"]:
            warnings.append(f"{label} could not be fetched right now, so it is not used in this answer.")
        elif step["result"].get("stale"):
            warnings.append(f"{label} is from an earlier fetch because its source is down.")

    missing = unmatched_figures(cleaned, trace)
    if missing:
        warnings.append(
            "Some figures in this answer could not be matched to fetched data: " + ", ".join(missing)
        )

    sources = source_lines(trace)
    if sources:
        cleaned += "\n\nSources:\n" + "\n".join(f"- {line}" for line in sources)
    else:
        warnings.append("No live data could be fetched, so this answer is general guidance only.")

    return {"advice": cleaned, "sources": sources, "warnings": warnings}
