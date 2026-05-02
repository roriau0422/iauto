"""Whisper transcription client.

OpenAI's `whisper-1` is the live model. Tests substitute
`FakeWhisperClient` so CI never burns minutes. Per arch §13.5: Whisper
ONLY for human-speech audio. Engine-sound recordings get routed to a
multimodal audio LLM in a later session.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Protocol

from openai import AsyncOpenAI

from app.platform.config import Settings
from app.platform.logging import get_logger

logger = get_logger("app.ai_mechanic.whisper")


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str | None
    audio_seconds: int


class WhisperClient(Protocol):
    async def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        language: str | None = None,
    ) -> TranscriptionResult: ...


class OpenAIWhisperClient:
    """Production client backed by `openai`'s Whisper endpoint.

    Falls back from `OPENAI_API_KEY` to `GEMINI_API_KEY` so the
    single-key dogfooding setup keeps working until OpenAI is fully
    routed through the same key as the agent.
    """

    def __init__(self, *, settings: Settings) -> None:
        api_key = settings.openai_api_key or settings.gemini_api_key
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY or GEMINI_API_KEY required for Whisper")
        self._client = AsyncOpenAI(api_key=api_key)
        # Whisper stays at `whisper-1` until OpenAI ships a v2; the env
        # override gives ops a swap-in lever once that lands.
        self._model = "whisper-1"

    async def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        # OpenAI's SDK accepts a `BytesIO` with a `.name` attribute as
        # the file parameter. `verbose_json` returns the duration so we
        # can bill by seconds without re-decoding the audio ourselves.
        buffer = io.BytesIO(audio_bytes)
        buffer.name = filename
        # Branch on `language` so each call site matches one of the
        # SDK's typed overloads. Forwarding kwargs as `**dict` defeats
        # the overload resolver and trips mypy.
        if language:
            response = await self._client.audio.transcriptions.create(
                model=self._model,
                file=buffer,
                response_format="verbose_json",
                language=language,
            )
        else:
            response = await self._client.audio.transcriptions.create(
                model=self._model,
                file=buffer,
                response_format="verbose_json",
            )
        text = getattr(response, "text", "") or ""
        detected = getattr(response, "language", None)
        duration = getattr(response, "duration", None)
        seconds = round(float(duration)) if duration is not None else 0
        return TranscriptionResult(
            text=text.strip(),
            language=str(detected) if detected else None,
            audio_seconds=seconds,
        )


class FakeWhisperClient:
    """Records calls and returns a canned transcription. Used in tests."""

    def __init__(
        self,
        *,
        text: str = "Mock transcript: brakes squealing.",
        language: str = "en",
        audio_seconds: int = 5,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.text = text
        self.language = language
        self.audio_seconds = audio_seconds

    async def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        self.calls.append(
            {
                "filename": filename,
                "byte_size": len(audio_bytes),
                "language": language,
            }
        )
        return TranscriptionResult(
            text=self.text,
            language=self.language,
            audio_seconds=self.audio_seconds,
        )
