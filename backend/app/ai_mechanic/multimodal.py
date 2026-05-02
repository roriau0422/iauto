"""Gemini multimodal client (vision + audio).

Per arch §13.5 the same Gemini multimodal endpoint serves two routes:
- Open-vocabulary visual Q&A (`what part is this`, damage assessment).
- Engine-sound diagnosis. Whisper is the wrong tool for non-speech
  audio; Gemini's audio modality understands mechanical signatures.

LiteLLM's `acompletion` accepts OpenAI-style multimodal message content
(`{type: "image_url", image_url: ...}` and `{type: "input_audio", ...}`),
which the Gemini provider transparently maps to its own format.

Tests substitute `FakeMultimodalClient` so CI never burns tokens.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Protocol

from app.platform.config import Settings
from app.platform.logging import get_logger

logger = get_logger("app.ai_mechanic.multimodal")


@dataclass(slots=True)
class MultimodalResult:
    text: str
    prompt_tokens: int
    completion_tokens: int


class MultimodalClient(Protocol):
    async def visual(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        image_mime: str,
    ) -> MultimodalResult: ...

    async def audio(
        self,
        *,
        prompt: str,
        audio_bytes: bytes,
        audio_mime: str,
    ) -> MultimodalResult: ...


VISUAL_MODEL = "gemini-multimodal-visual"
AUDIO_MODEL = "gemini-multimodal-audio"


class GeminiMultimodalClient:
    """Production client. Routes through LiteLLM's `acompletion`.

    Lazy-imports `litellm` so test environments that mock the client
    don't pay the heavy import cost. The model name shipped at the
    spend log is a stable internal label (`gemini-multimodal-visual`
    / `-audio`) decoupled from the concrete LiteLLM model string —
    that lets us swap the underlying model in `Settings` without
    breaking the spend dashboard's grouping.
    """

    def __init__(self, *, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY required for multimodal calls")
        self.settings = settings

    async def visual(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        image_mime: str,
    ) -> MultimodalResult:
        import litellm

        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{image_mime};base64,{b64}"
        response = await litellm.acompletion(
            model=self.settings.ai_mechanic_model,
            api_key=self.settings.gemini_api_key,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        )
        return _parse_response(response)

    async def audio(
        self,
        *,
        prompt: str,
        audio_bytes: bytes,
        audio_mime: str,
    ) -> MultimodalResult:
        import litellm

        b64 = base64.b64encode(audio_bytes).decode("ascii")
        # Gemini accepts audio inline via the `input_audio` content
        # block. LiteLLM forwards it untouched.
        response = await litellm.acompletion(
            model=self.settings.ai_mechanic_model,
            api_key=self.settings.gemini_api_key,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": b64,
                                "format": audio_mime.split("/")[-1],
                            },
                        },
                    ],
                }
            ],
        )
        return _parse_response(response)


def _parse_response(response: object) -> MultimodalResult:
    """Pull text + token counts off a LiteLLM completion response."""
    text = ""
    choices = getattr(response, "choices", None)
    if choices:
        first = choices[0]
        message = getattr(first, "message", None)
        if message is not None:
            text = getattr(message, "content", "") or ""
    usage = getattr(response, "usage", None)
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
    return MultimodalResult(
        text=str(text).strip(),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


class FakeMultimodalClient:
    """Test stub — records calls and returns a canned reply."""

    def __init__(
        self,
        *,
        text: str = "Mock multimodal reply.",
        prompt_tokens: int = 80,
        completion_tokens: int = 25,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.text = text
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    async def visual(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        image_mime: str,
    ) -> MultimodalResult:
        self.calls.append(
            {
                "kind": "visual",
                "prompt": prompt,
                "byte_size": len(image_bytes),
                "mime": image_mime,
            }
        )
        return MultimodalResult(
            text=self.text,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )

    async def audio(
        self,
        *,
        prompt: str,
        audio_bytes: bytes,
        audio_mime: str,
    ) -> MultimodalResult:
        self.calls.append(
            {
                "kind": "audio",
                "prompt": prompt,
                "byte_size": len(audio_bytes),
                "mime": audio_mime,
            }
        )
        return MultimodalResult(
            text=self.text,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )
