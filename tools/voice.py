"""Natural voice for answers, from ElevenLabs.

Needs VOICE_API (the ElevenLabs key) in .env. Optional: ELEVENLABS_VOICE_ID picks the voice.
The free ElevenLabs plan cannot use library voices through the API, so until the account is
upgraded the request fails with a clear reason and the page falls back to the browser's voice.
The key is only sent in a request header and never appears in an error message.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

API = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
MODEL = "eleven_multilingual_v2"  # handles Hindi and English in one model
TIMEOUT_SECONDS = 30
MAX_CHARS = 1000
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"


class VoiceError(Exception):
    """Speech could not be produced. The message is safe to show the user."""


def synthesize(text: str) -> bytes:
    """Return MP3 audio for the text."""
    key = os.getenv("VOICE_API", "").strip()
    if not key:
        raise VoiceError("Natural voice is not set up. The phone's voice is used instead.")
    text = text.strip()[:MAX_CHARS]
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip() or DEFAULT_VOICE_ID
    try:
        response = requests.post(
            API.format(voice_id=voice_id),
            headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
            json={"text": text, "model_id": MODEL},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise VoiceError(f"Natural voice is unreachable ({type(error).__name__}).") from error
    if response.status_code == 200 and response.content:
        return response.content
    reason = ""
    try:
        reason = response.json().get("detail", {}).get("code", "")
    except ValueError:
        pass
    if response.status_code == 402 or reason == "paid_plan_required":
        raise VoiceError("Natural voice needs a paid ElevenLabs plan. The phone's voice is used instead.")
    raise VoiceError(f"Natural voice is unavailable (HTTP {response.status_code}). The phone's voice is used instead.")
