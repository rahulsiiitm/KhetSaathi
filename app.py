"""FastAPI app: serves the farmer page and the /advise endpoint."""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from agent import AgentError, advise
from tools.mandi import SUPPORTED_CROPS

load_dotenv()

BASE_DIR = Path(__file__).parent
app = FastAPI(title="KhetSaathi")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class AdviceRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    place: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=60)
    crop: str

    @field_validator("question", "place", "state")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("crop")
    @classmethod
    def known_crop(cls, value: str) -> str:
        if value not in SUPPORTED_CROPS:
            raise ValueError(f"Crop must be one of: {', '.join(SUPPORTED_CROPS)}.")
        return value


@app.get("/")
def home() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "crops": SUPPORTED_CROPS}


@app.post("/advise")
def advise_endpoint(request: AdviceRequest) -> dict:
    try:
        return advise(request.question, request.place, request.state, request.crop)
    except AgentError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
