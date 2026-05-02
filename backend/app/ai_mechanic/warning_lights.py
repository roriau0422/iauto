"""Dashboard-warning-light classifier.

Per arch §13.5: warning lights have a *finite* vocabulary (~150 icons),
so the right tool is a fine-tuned MobileNet/EfficientNet — NOT CLIP
zero-shot.

Phase 3 ships the contract and audit trail. The runtime classifier here
is a deterministic placeholder (`HashHeuristicClassifier`) that maps
the SHA-256 of the image bytes to the seeded taxonomy. Phase 5 swaps
it out for an ONNX-served MobileNet trained on a Mongolian-fleet
dashboard dataset; the `Classifier` Protocol is the seam.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class WarningLightPrediction:
    code: str
    confidence: float


@dataclass(slots=True)
class ClassificationResult:
    model: str
    predictions: list[WarningLightPrediction]

    @property
    def top_code(self) -> str | None:
        return self.predictions[0].code if self.predictions else None


class WarningLightClassifier(Protocol):
    async def classify(
        self,
        *,
        image_bytes: bytes,
        candidate_codes: list[str],
    ) -> ClassificationResult: ...


class HashHeuristicClassifier:
    """Deterministic placeholder until the ONNX MobileNet ships.

    Maps `sha256(image_bytes)` → an index into `candidate_codes` and
    fakes a confidence. Stable across runs so tests + dogfooding both
    behave reproducibly. Identifier in the spend log is
    `warning-light-heuristic-v1` so phase 5 telemetry can spot rows
    that ran on the placeholder.
    """

    name = "warning-light-heuristic-v1"

    async def classify(
        self,
        *,
        image_bytes: bytes,
        candidate_codes: list[str],
    ) -> ClassificationResult:
        if not candidate_codes:
            return ClassificationResult(model=self.name, predictions=[])
        digest = hashlib.sha256(image_bytes).digest()
        primary_index = digest[0] % len(candidate_codes)
        secondary_index = (digest[1] % (len(candidate_codes) - 1) + 1 + primary_index) % len(
            candidate_codes
        )
        # Confidence drawn from byte-2 of the digest, scaled to [0.55, 0.95].
        primary_conf = 0.55 + (digest[2] / 255.0) * 0.40
        secondary_conf = max(0.05, primary_conf * 0.4)
        return ClassificationResult(
            model=self.name,
            predictions=[
                WarningLightPrediction(
                    code=candidate_codes[primary_index],
                    confidence=round(primary_conf, 3),
                ),
                WarningLightPrediction(
                    code=candidate_codes[secondary_index],
                    confidence=round(secondary_conf, 3),
                ),
            ],
        )


class FakeWarningLightClassifier:
    """Test stub — returns whatever the test pre-loads on `next_result`."""

    name = "warning-light-fake"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.next_result: ClassificationResult | None = None

    async def classify(
        self,
        *,
        image_bytes: bytes,
        candidate_codes: list[str],
    ) -> ClassificationResult:
        self.calls.append({"byte_size": len(image_bytes), "candidate_count": len(candidate_codes)})
        if self.next_result is not None:
            return self.next_result
        # Fall back to the heuristic so the test still gets a reasonable
        # result without scripting `next_result` on every test.
        return await HashHeuristicClassifier().classify(
            image_bytes=image_bytes, candidate_codes=candidate_codes
        )
