"""FastAPI app: serves the farmer page and the /advise endpoint."""

import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import store
from agent import AgentError, advise
from tools.cache import SourceDown
from tools.mandi import list_crops, match_crop
from tools.places import LocationError, nearest_markets, reverse_geocode
from tools.voice import VoiceError, synthesize

load_dotenv()

BASE_DIR = Path(__file__).parent
app = FastAPI(title="KhetSaathi")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


MAX_HISTORY_TURNS = 4


class PastTurn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=3000)


class AdviceRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    place: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=60)
    crop: str
    # Exact position from the farmer's phone, when they allow it. Weather uses these coordinates.
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    # Earlier turns in this conversation, oldest first. Only the last few are sent to the model.
    history: list[PastTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)

    @field_validator("question", "place", "state")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("crop")
    @classmethod
    def crop_name(cls, value: str) -> str:
        # Any crop name the market data might use. Unknown crops get a clear "no data" answer later.
        value = value.strip()
        if len(value) < 2 or len(value) > 60:
            raise ValueError("Crop name must be between 2 and 60 characters.")
        return value


@app.get("/")
def home() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/crops")
def crops() -> dict:
    """Crop names the market data uses, for the crop suggestions on the page."""
    return {"crops": list_crops()}


@app.post("/advise")
def advise_endpoint(request: AdviceRequest) -> dict:
    started = time.perf_counter()
    coords = None
    if request.latitude is not None and request.longitude is not None:
        coords = f"{request.latitude:.4f},{request.longitude:.4f}"
    try:
        history = [(turn.question, turn.answer) for turn in request.history]
        result = advise(request.question, request.place, request.state, request.crop, history, coords)
    except AgentError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    markets = []
    if coords:
        rows = store.mandi_rows_for(request.state, request.place, match_crop(request.crop))
        try:
            markets = nearest_markets(request.latitude, request.longitude, request.state, request.place, rows)
        except SourceDown:
            markets = []  # the map lookup is optional; the advice still stands
    latency_ms = round((time.perf_counter() - started) * 1000)
    tools_used = [step["tool"] for step in result["trace"]]
    store.log_advice(
        request.place, request.crop, request.question, result["advice"],
        result["warnings"], tools_used, latency_ms,
    )
    return {**result, "markets": markets, "latency_ms": latency_ms}


class LocateRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


@app.post("/locate")
def locate(request: LocateRequest) -> dict:
    """Turn the phone's position into a village, district, and state the farmer can confirm."""
    try:
        return reverse_geocode(request.latitude, request.longitude)
    except LocationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SourceDown:
        raise HTTPException(status_code=503, detail="The location service is busy. Type your village instead.")


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@app.post("/speak")
def speak(request: SpeakRequest) -> Response:
    """Natural-voice audio for an answer. On failure the page uses the phone's own voice."""
    try:
        return Response(content=synthesize(request.text), media_type="audio/mpeg")
    except VoiceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/status")
def status() -> dict:
    """Health of each data source, cache size, and answer statistics."""
    return {
        "sources": store.health_snapshot(),
        "cache": store.cache_stats(),
        "answers": store.advice_stats(),
    }
