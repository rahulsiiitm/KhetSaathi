"""The advisory agent: a Gemini chat with live data tools.

The SDK calls the tools the model asks for, sends the results back, and repeats
until the model writes an answer, up to MAX_ROUNDS tool calls.
Tool errors are returned to the model as data, so it must say what is missing.
"""

import os
import re
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ServerError

from risk import assess
from safety import check_answer
from tools.cache import SourceDown
from tools.mandi import MandiError, get_mandi_prices
from tools.weather import WeatherError, get_weather

load_dotenv()

MAX_ROUNDS = 4
LLM_ATTEMPTS = 2
LLM_RETRY_SECONDS = 2
LLM_TIMEOUT_MS = 30_000

SYSTEM_PROMPT = """You are a sensible, experienced agriculture advisor from the farmer's own district. You
talk the way a respected neighbour who knows farming talks: direct, warm, specific, and unhurried. You are
not a report generator and not a chatbot.

How to sound like a person:
- Open with the answer itself, in the first sentence. Example: "Haan, aaj sinchai kar dijiye." or
  "Yes, irrigate today, not tomorrow." Never open with "Based on", "According to", "Certainly", or "Great question".
- Speak to the farmer as "aap" (Hindi) or "you" (English). Use their crop and their place by name.
- Use weekday names and simple dates people use: "Friday (31 Oct)", "kal" or "parso" in Hindi.
- Short sentences. Everyday words. Explain any technical term in a few words the first time.
- Say what you would do in their place, and why, in one line. Never list every fact the tools returned.
- Do not say you are an AI or a tool, and do not mention "the data shows" or "the tool returned".
- No emojis, no bold, no headings beyond the labels below.
- Never write rule codes such as R4 in the answer. The sources list shows them; the farmer does not need them.

Rules:
- Use the tools to get live weather, field risks, and mandi prices before giving advice that depends on them.
- Risks come only from the assess_field_risk tool. Quote each risk with its rule ID (R1 to R5). Do not
  add risks of your own.
- If a result says "stale" or "cache", tell the farmer how old that data is.
- Use only numbers that a tool returned. Never invent prices, rainfall, or dates.
- If a tool returns an error, say that this data is unavailable and do not guess it.
- Answer in this structure, with the labels exactly as written. Each line is plain, human speech:
  Decision: the one thing to do, said as a person would say it, with the reason in the same sentence.
  Day-by-day plan: one line per forecast day, written as "Weekday (date): what the day is good for, in plain words".
  Based on: two or three short plain-language reasons, for example "rain is not expected for three days".
  Not known: what could not be checked, and what the farmer should look at in their own field.
- If mandi prices are stale or missing, say so in "Not known" and do not give a price-based sell decision.
- Never give chemical doses, pesticide amounts, or medical advice. Refer farmers to their
  local Krishi Vigyan Kendra or agriculture officer for chemicals.
- Reply in the language the farmer wrote in: English for an English question, Hindi for a Hindi question.
  Keep it short and plain.
"""


class AgentError(Exception):
    """The AI service could not produce an answer. The message is safe to show the user."""


def reply_language(question: str) -> str:
    """Hindi if the question contains Devanagari script, otherwise English."""
    return "Hindi" if re.search(r"[ऀ-ॿ]", question) else "English"


def run_tool(name: str, args: dict) -> dict:
    """Run one tool. Errors become data the model must report, not exceptions."""
    try:
        if name == "get_weather":
            return get_weather(args["place"])
        if name == "assess_field_risk":
            weather = get_weather(args["place"])
            return {
                "place": weather["place"],
                "risks": assess(weather["forecast"]),
                "rules": "R1 heavy rain, R2 heat, R3 cold, R4 low-rain field window, R5 dry warm spell",
                "source": "KhetSaathi rule engine on Open-Meteo forecast",
                "fetched_at": weather["fetched_at"],
                "cache": weather["cache"],
                "stale": weather["stale"],
            }
        if name == "get_mandi_prices":
            return get_mandi_prices(args["state"], args["district"], args["commodity"])
        return {"error": f"Unknown tool '{name}'."}
    except (WeatherError, MandiError, SourceDown) as error:
        return {"error": str(error)}
    except KeyError as error:
        return {"error": f"Missing argument {error}."}


HISTORY_ANSWER_CHARS = 600


def build_request(question: str, place: str, state: str, crop: str,
                  history: list[tuple[str, str]] | None = None, coords: str | None = None) -> str:
    """Build the message for the model. Earlier turns give it context for follow-up questions."""
    lines = []
    if history:
        lines.append("Earlier in this conversation (use it only for context; get fresh data with the tools):")
        for past_question, past_answer in history:
            lines.append(f"Farmer: {past_question}")
            lines.append(f"KhetSaathi: {past_answer[:HISTORY_ANSWER_CHARS]}")
        lines.append("")
    lines += [
        f"Farmer's question: {question}",
        f"Village or town: {place}",
        f"State: {state}",
        f"Crop: {crop}",
    ]
    if coords:
        lines.append(f"Exact position from the farmer's phone: {coords}. "
                     "Use this exact position as the place when you call get_weather.")
    lines += [
        "Use district = the village or town name if no district is known.",
        f"Reply in {reply_language(question)}.",
    ]
    return "\n".join(lines)


def advise(question: str, place: str, state: str, crop: str,
           history: list[tuple[str, str]] | None = None, coords: str | None = None) -> dict:
    """Answer one farmer's question using live tools, then apply the guardrails."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "").strip()
    if not api_key:
        raise AgentError("The AI service is not configured: GEMINI_API_KEY is not set.")
    if not model:
        raise AgentError("The AI service is not configured: GEMINI_MODEL is not set.")

    trace = []

    def weather_tool(place: str) -> dict:
        """Live 3-day weather forecast (rain and temperature) for a village, town, or district in India.

        Args:
            place: Village, town, or district name.
        """
        args = {"place": place}
        result = run_tool("get_weather", args)
        trace.append({"tool": "get_weather", "args": args, "result": result})
        return result

    def mandi_tool(state: str, district: str, commodity: str) -> dict:
        """Latest market (mandi) prices per quintal for a crop in a district.

        Args:
            state: State name, e.g. Punjab.
            district: District name.
            commodity: Crop name as the market data spells it, e.g. Potato, Tomato, Onion.
        """
        args = {"state": state, "district": district, "commodity": commodity}
        result = run_tool("get_mandi_prices", args)
        trace.append({"tool": "get_mandi_prices", "args": args, "result": result})
        return result

    def risk_tool(place: str) -> dict:
        """Field risks (heavy rain, heat, cold, spray window, dry spell) computed by fixed rules from the forecast.

        Args:
            place: Village, town, or district name.
        """
        args = {"place": place}
        result = run_tool("assess_field_risk", args)
        trace.append({"tool": "assess_field_risk", "args": args, "result": result})
        return result

    # Give up on a hung connection so the farmer never waits on a stuck request.
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=LLM_TIMEOUT_MS))
    # The SDK runs the tool loop itself. Gemini 3 models need the SDK to keep their
    # thought signatures, which a hand-written loop drops.
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[weather_tool, risk_tool, mandi_tool],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            maximum_remote_calls=MAX_ROUNDS
        ),
        temperature=0.2,
    )
    request = build_request(question, place, state, crop, history, coords)

    response = None
    for attempt in range(LLM_ATTEMPTS):
        try:
            chat = client.chats.create(model=model, config=config)
            response = chat.send_message(request)
            break
        except ServerError as error:
            # Gemini's own server errors are often brief. Retry once after a pause.
            if attempt + 1 == LLM_ATTEMPTS:
                raise AgentError("The AI service is busy right now. Please try again in a moment.") from error
            time.sleep(LLM_RETRY_SECONDS)
        except Exception as error:  # other SDK errors become one safe message
            raise AgentError(f"The AI service failed: {type(error).__name__}. Try again.") from error

    answer = response.text
    if not answer:
        raise AgentError("The AI service did not finish the answer. Try a shorter question.")

    result = check_answer(answer, trace)
    result["trace"] = trace
    return result
