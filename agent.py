"""The advisory agent: a Gemini chat with live data tools.

The SDK calls the tools the model asks for, sends the results back, and repeats
until the model writes an answer, up to MAX_ROUNDS tool calls.
Tool errors are returned to the model as data, so it must say what is missing.
"""

import os
import re

from dotenv import load_dotenv
from google import genai
from google.genai import types

from safety import check_answer
from tools.mandi import MandiError, get_mandi_prices
from tools.weather import WeatherError, get_weather

load_dotenv()

MAX_ROUNDS = 4

SYSTEM_PROMPT = """You are KhetSaathi, an advisor for Indian farmers.

Rules:
- Use the tools to get live weather and mandi prices before giving advice that depends on them.
- Use only numbers that a tool returned. Never invent prices, rainfall, or dates.
- If a tool returns an error, say that this data is unavailable and do not guess it.
- Give practical, dated steps (spray, irrigate, wait, harvest, or sell) based on the data.
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
        if name == "get_mandi_prices":
            return get_mandi_prices(args["state"], args["district"], args["commodity"])
        return {"error": f"Unknown tool '{name}'."}
    except (WeatherError, MandiError) as error:
        return {"error": str(error)}
    except KeyError as error:
        return {"error": f"Missing argument {error}."}


def advise(question: str, place: str, state: str, crop: str) -> dict:
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
            commodity: Crop name, one of: Potato, Tomato, Onion, Cauliflower, Paddy(Common).
        """
        args = {"state": state, "district": district, "commodity": commodity}
        result = run_tool("get_mandi_prices", args)
        trace.append({"tool": "get_mandi_prices", "args": args, "result": result})
        return result

    client = genai.Client(api_key=api_key)
    # The SDK runs the tool loop itself. Gemini 3 models need the SDK to keep their
    # thought signatures, which a hand-written loop drops.
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[weather_tool, mandi_tool],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            maximum_remote_calls=MAX_ROUNDS
        ),
        temperature=0.2,
    )
    request = (
        f"Farmer's question: {question}\n"
        f"Village or town: {place}\n"
        f"State: {state}\n"
        f"Crop: {crop}\n"
        f"Use district = the village or town name if no district is known.\n"
        f"Reply in {reply_language(question)}."
    )

    try:
        chat = client.chats.create(model=model, config=config)
        response = chat.send_message(request)
    except Exception as error:  # the SDK raises several error types; all become one safe message
        raise AgentError(f"The AI service failed: {type(error).__name__}. Try again.") from error

    answer = response.text
    if not answer:
        raise AgentError("The AI service did not finish the answer. Try a shorter question.")

    result = check_answer(answer, trace)
    result["trace"] = trace
    return result
