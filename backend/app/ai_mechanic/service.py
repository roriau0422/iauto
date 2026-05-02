"""AI Mechanic service — sessions, messages, agent dispatch, KB ingestion."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_mechanic.agent import (
    AgentContext,
    AgentRunner,
    AgentRunResult,
)
from app.ai_mechanic.embeddings import EmbeddingClient, content_hash
from app.ai_mechanic.models import (
    AiMessage,
    AiMessageRole,
    AiMultimodalCall,
    AiMultimodalKind,
    AiSession,
    AiVoiceTranscript,
    AiWarningLightPrediction,
)
from app.ai_mechanic.multimodal import (
    AUDIO_MODEL,
    VISUAL_MODEL,
    MultimodalClient,
)
from app.ai_mechanic.rate_limit import AiRateLimiter
from app.ai_mechanic.repository import (
    AiEmbeddingCacheRepository,
    AiKbRepository,
    AiMessageRepository,
    AiMultimodalCallRepository,
    AiSessionRepository,
    AiSpendRepository,
    AiVoiceTranscriptRepository,
    AiWarningLightPredictionRepository,
    AiWarningLightTaxonomyRepository,
)
from app.ai_mechanic.schemas import (
    EngineSoundMessageCreateIn,
    KbDocumentCreateIn,
    MessageCreateIn,
    SessionCreateIn,
    VisualMessageCreateIn,
    VoiceMessageCreateIn,
    WarningLightMessageCreateIn,
)
from app.ai_mechanic.spend import estimate_cost_micro_mnt
from app.ai_mechanic.warning_lights import WarningLightClassifier
from app.ai_mechanic.whisper import WhisperClient
from app.media.models import MediaAsset, MediaAssetPurpose, MediaAssetStatus
from app.platform.config import Settings
from app.platform.errors import ConflictError, NotFoundError
from app.platform.logging import get_logger

logger = get_logger("app.ai_mechanic.service")

# Roughly: 250–500 tokens per chunk produces clean retrieval at the
# cost of more rows. We split on paragraph breaks and pack into ~1500
# chars per chunk; cheap heuristic, replaceable later if recall suffers.
KB_CHUNK_CHAR_TARGET = 1_500


def _chunk(body: str) -> list[str]:
    """Naive paragraph-aware chunker. Replace later with a real tokenizer."""
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    if not paragraphs:
        return [body.strip()] if body.strip() else []
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for para in paragraphs:
        if buf_len + len(para) > KB_CHUNK_CHAR_TARGET and buf:
            chunks.append("\n\n".join(buf))
            buf = [para]
            buf_len = len(para)
        else:
            buf.append(para)
            buf_len += len(para) + 2
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


@dataclass(slots=True)
class IngestResult:
    document_id: uuid.UUID
    chunks_added: int
    embeddings_cached: int


@dataclass(slots=True)
class AssistantReply:
    user_message: AiMessage
    assistant_message: AiMessage
    prompt_tokens: int
    completion_tokens: int
    est_cost_micro_mnt: int


@dataclass(slots=True)
class VoiceReply:
    transcript: AiVoiceTranscript
    user_message: AiMessage
    assistant_message: AiMessage
    prompt_tokens: int
    completion_tokens: int
    transcription_micro_mnt: int
    agent_micro_mnt: int


@dataclass(slots=True)
class WarningLightReply:
    prediction: AiWarningLightPrediction
    labels: list[dict[str, Any]]
    user_message: AiMessage
    assistant_message: AiMessage
    prompt_tokens: int
    completion_tokens: int
    classifier_micro_mnt: int
    agent_micro_mnt: int


@dataclass(slots=True)
class MultimodalReply:
    call: AiMultimodalCall
    user_message: AiMessage
    assistant_message: AiMessage
    prompt_tokens: int
    completion_tokens: int
    multimodal_micro_mnt: int
    agent_micro_mnt: int


WHISPER_MODEL_NAME = "whisper-1"
# Confidence floor for surfacing a label to the LLM. Anything below
# this gets dropped from the user-message summary so the agent doesn't
# chase 0.05-confidence noise.
WARNING_LIGHT_CONFIDENCE_FLOOR = 0.20

# Default prompt for engine-sound diagnosis when the caller doesn't
# supply one. Keeps the audio LLM grounded in the diagnostic frame.
ENGINE_SOUND_DEFAULT_PROMPT = (
    "You are an experienced auto mechanic. Listen to this engine "
    "recording and identify the most likely mechanical fault. Be "
    "specific (component, symptom). If the audio is unclear, say so."
)


class AiMechanicService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        redis: Redis,
        runner: AgentRunner,
        embeddings: EmbeddingClient,
        settings: Settings,
        whisper: WhisperClient | None = None,
        media_download: object | None = None,
        warning_light_classifier: WarningLightClassifier | None = None,
        multimodal: MultimodalClient | None = None,
    ) -> None:
        self.session = session
        self.runner = runner
        self.embeddings = embeddings
        self.settings = settings
        self.whisper = whisper
        # `media_download` is the optional `MediaClient`-shaped fetcher
        # used to pull audio/image bytes for AI ingestion. Passed in
        # so the voice + warning-light + multimodal paths don't have to
        # import a fresh S3 client per request.
        self.media_download = media_download
        self.warning_light_classifier = warning_light_classifier
        self.multimodal = multimodal
        self.kb = AiKbRepository(session)
        self.cache = AiEmbeddingCacheRepository(session)
        self.sessions = AiSessionRepository(session)
        self.messages = AiMessageRepository(session)
        self.spend = AiSpendRepository(session)
        self.transcripts = AiVoiceTranscriptRepository(session)
        self.warning_light_taxonomy = AiWarningLightTaxonomyRepository(session)
        self.warning_light_predictions = AiWarningLightPredictionRepository(session)
        self.multimodal_calls = AiMultimodalCallRepository(session)
        self.rate_limiter = AiRateLimiter(
            redis=redis, daily_limit=settings.ai_daily_request_limit_per_user
        )

    # ---- KB ingestion --------------------------------------------------

    async def ingest_document(self, *, payload: KbDocumentCreateIn) -> IngestResult:
        """Idempotent ingest: same content_hash → return existing document.

        Each chunk is embedded once via the configured client, cached in
        `ai_embedding_cache` keyed on `(scope=kb_document, doc_id, hash)`,
        and persisted into `ai_kb_chunks` with the embedding column.
        """
        h = content_hash(payload.body)
        existing = await self.kb.get_document_by_hash(h)
        if existing is not None:
            return IngestResult(document_id=existing.id, chunks_added=0, embeddings_cached=0)

        document = await self.kb.create_document(
            title=payload.title,
            body=payload.body,
            content_hash=h,
            source_url=payload.source_url,
            language=payload.language,
            vehicle_brand_id=payload.vehicle_brand_id,
            vehicle_model_id=payload.vehicle_model_id,
        )

        chunks = _chunk(payload.body)
        if not chunks:
            return IngestResult(document_id=document.id, chunks_added=0, embeddings_cached=0)

        # Cache lookup per chunk before hitting the network.
        to_embed_indexes: list[int] = []
        embeddings: list[list[float]] = [[] for _ in chunks]
        for i, chunk_body in enumerate(chunks):
            ch = content_hash(chunk_body)
            cached = await self.cache.get(
                scope_kind="kb_document",
                scope_id=document.id,
                content_hash=ch,
            )
            if cached is not None:
                embeddings[i] = cached
            else:
                to_embed_indexes.append(i)

        if to_embed_indexes:
            fresh = await self.embeddings.embed(texts=[chunks[i] for i in to_embed_indexes])
            for slot_index, real_index in enumerate(to_embed_indexes):
                embeddings[real_index] = fresh[slot_index]
                await self.cache.put(
                    scope_kind="kb_document",
                    scope_id=document.id,
                    content_hash=content_hash(chunks[real_index]),
                    embedding=fresh[slot_index],
                )

        for i, (chunk_body, emb) in enumerate(zip(chunks, embeddings, strict=True)):
            await self.kb.insert_chunk(
                document_id=document.id,
                chunk_index=i,
                body=chunk_body,
                embedding=emb,
            )

        logger.info(
            "ai_kb_document_ingested",
            document_id=str(document.id),
            chunks_added=len(chunks),
            embeddings_called=len(to_embed_indexes),
        )
        return IngestResult(
            document_id=document.id,
            chunks_added=len(chunks),
            embeddings_cached=len(to_embed_indexes),
        )

    # ---- Sessions + messages -------------------------------------------

    async def create_session(self, *, user_id: uuid.UUID, payload: SessionCreateIn) -> AiSession:
        return await self.sessions.create(
            user_id=user_id,
            vehicle_id=payload.vehicle_id,
            title=payload.title,
        )

    async def list_sessions(
        self, *, user_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[AiSession], int]:
        return await self.sessions.list_for_user(user_id=user_id, limit=limit, offset=offset)

    async def get_session_for_user(self, *, session_id: uuid.UUID, user_id: uuid.UUID) -> AiSession:
        sess = await self.sessions.get_for_user(session_id=session_id, user_id=user_id)
        if sess is None:
            raise NotFoundError("Session not found")
        return sess

    async def list_messages(self, *, session_id: uuid.UUID, user_id: uuid.UUID) -> list[AiMessage]:
        await self.get_session_for_user(session_id=session_id, user_id=user_id)
        return await self.messages.list_for_session(session_id=session_id)

    async def post_user_message(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: MessageCreateIn,
    ) -> AssistantReply:
        """Persist the user's message, run the agent, persist the reply."""
        sess = await self.get_session_for_user(session_id=session_id, user_id=user_id)
        await self.rate_limiter.check_and_consume(user_id=user_id)
        return await self._dispatch_agent(session=sess, user_id=user_id, content=payload.content)

    async def _dispatch_agent(
        self,
        *,
        session: AiSession,
        user_id: uuid.UUID,
        content: str,
    ) -> AssistantReply:
        """Common agent-dispatch path used by text and voice entry points.

        Persists the user message, runs the agent against the prior
        history, persists the assistant reply + any tool rows, records
        the spend event, and returns an `AssistantReply`.
        """
        session_id = session.id

        user_msg = await self.messages.append(
            session_id=session_id,
            role=AiMessageRole.user,
            content=content,
        )

        # Build agent history from prior messages. Only roles the LLM
        # understands are forwarded — we drop tool rows because they're
        # an implementation detail of our own persistence.
        prior = await self.messages.list_for_session(session_id=session_id)
        history: list[dict[str, str]] = []
        for m in prior[:-1]:  # exclude the just-inserted user message
            if m.role in (AiMessageRole.user, AiMessageRole.assistant):
                history.append({"role": m.role.value, "content": m.content})

        ctx = AgentContext(
            session=self.session,
            user_id=user_id,
            vehicle_id=session.vehicle_id,
            embedding_client=self.embeddings,
        )
        run: AgentRunResult = await self.runner.run(ctx=ctx, history=history, user_input=content)

        assistant_msg = await self.messages.append(
            session_id=session_id,
            role=AiMessageRole.assistant,
            content=run.final_output,
        )

        for call in run.tool_calls:
            await self.messages.append(
                session_id=session_id,
                role=AiMessageRole.tool,
                content="",
                tool_name=str(call.get("name") or "unknown"),
                tool_payload=call,
            )

        cost = estimate_cost_micro_mnt(
            model=self.settings.ai_mechanic_model,
            prompt_tokens=run.prompt_tokens,
            completion_tokens=run.completion_tokens,
        )
        await self.spend.record(
            user_id=user_id,
            session_id=session_id,
            model=self.settings.ai_mechanic_model,
            prompt_tokens=run.prompt_tokens,
            completion_tokens=run.completion_tokens,
            est_cost_micro_mnt=cost,
        )

        logger.info(
            "ai_message_handled",
            session_id=str(session_id),
            user_id=str(user_id),
            prompt_tokens=run.prompt_tokens,
            completion_tokens=run.completion_tokens,
            tool_calls=len(run.tool_calls),
            est_cost_micro_mnt=cost,
        )
        return AssistantReply(
            user_message=user_msg,
            assistant_message=assistant_msg,
            prompt_tokens=run.prompt_tokens,
            completion_tokens=run.completion_tokens,
            est_cost_micro_mnt=cost,
        )

    async def post_voice_message(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: VoiceMessageCreateIn,
    ) -> VoiceReply:
        """Voice → text via Whisper, then thread through the agent.

        The voice flow consumes the same daily request budget as a text
        message — a tap of the mic shouldn't cost more quota than a
        typed turn. Whisper spend rolls into `ai_spend_events` with
        `audio_seconds` populated; the agent run logs its own row as
        usual.
        """
        if self.whisper is None or self.media_download is None:
            raise ConflictError("Voice transcription is not configured")

        sess = await self.get_session_for_user(session_id=session_id, user_id=user_id)
        await self.rate_limiter.check_and_consume(user_id=user_id)

        asset = await self.session.get(MediaAsset, payload.media_asset_id)
        if asset is None or asset.owner_id != user_id:
            raise NotFoundError("Asset not found")
        if asset.purpose != MediaAssetPurpose.voice:
            raise ConflictError("Asset purpose is not voice")
        if asset.status != MediaAssetStatus.active:
            raise ConflictError("Asset is not active; confirm the upload first")

        # Pull bytes from MinIO. The boto3 GET is sync so the client
        # implementation wraps it in `asyncio.to_thread`.
        download = self.media_download.download_bytes  # type: ignore[attr-defined]
        audio_bytes = await download(object_key=asset.object_key)

        # Use the asset's basename as the filename so OpenAI infers the
        # codec from the extension.
        filename = asset.object_key.rsplit("/", 1)[-1]
        whisper_result = await self.whisper.transcribe(
            audio_bytes=audio_bytes,
            filename=filename,
            language=payload.language,
        )
        if not whisper_result.text.strip():
            raise ConflictError("Whisper returned an empty transcript")

        transcript_row = await self.transcripts.create(
            session_id=sess.id,
            user_id=user_id,
            media_asset_id=asset.id,
            model=WHISPER_MODEL_NAME,
            text=whisper_result.text,
            language=whisper_result.language,
            audio_seconds=whisper_result.audio_seconds,
        )

        transcription_cost = estimate_cost_micro_mnt(
            model=WHISPER_MODEL_NAME,
            prompt_tokens=0,
            completion_tokens=0,
            audio_seconds=whisper_result.audio_seconds,
        )
        await self.spend.record(
            user_id=user_id,
            session_id=sess.id,
            model=WHISPER_MODEL_NAME,
            prompt_tokens=0,
            completion_tokens=0,
            audio_seconds=whisper_result.audio_seconds,
            est_cost_micro_mnt=transcription_cost,
        )

        agent_reply = await self._dispatch_agent(
            session=sess, user_id=user_id, content=whisper_result.text
        )
        logger.info(
            "ai_voice_transcribed",
            session_id=str(sess.id),
            transcript_id=str(transcript_row.id),
            audio_seconds=whisper_result.audio_seconds,
            transcription_micro_mnt=transcription_cost,
        )
        return VoiceReply(
            transcript=transcript_row,
            user_message=agent_reply.user_message,
            assistant_message=agent_reply.assistant_message,
            prompt_tokens=agent_reply.prompt_tokens,
            completion_tokens=agent_reply.completion_tokens,
            transcription_micro_mnt=transcription_cost,
            agent_micro_mnt=agent_reply.est_cost_micro_mnt,
        )

    async def post_warning_light_message(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: WarningLightMessageCreateIn,
    ) -> WarningLightReply:
        """Classify a dashboard photo, then thread the labels through the agent.

        The classifier returns a top-K of `(code, confidence)` over the
        seeded vocabulary. We persist the audit row, drop low-confidence
        labels, hydrate the displays from the taxonomy table, and post a
        compact system-prefixed user message into the conversation so the
        LLM has structured findings to ground its diagnosis.
        """
        if self.warning_light_classifier is None or self.media_download is None:
            raise ConflictError("Warning-light classification is not configured")

        sess = await self.get_session_for_user(session_id=session_id, user_id=user_id)
        await self.rate_limiter.check_and_consume(user_id=user_id)

        asset = await self.session.get(MediaAsset, payload.media_asset_id)
        if asset is None or asset.owner_id != user_id:
            raise NotFoundError("Asset not found")
        if asset.purpose != MediaAssetPurpose.warning_light:
            raise ConflictError("Asset purpose is not warning_light")
        if asset.status != MediaAssetStatus.active:
            raise ConflictError("Asset is not active; confirm the upload first")

        candidate_codes = await self.warning_light_taxonomy.list_codes()
        if not candidate_codes:
            raise ConflictError("Warning-light taxonomy is empty; seed the table")

        download = self.media_download.download_bytes  # type: ignore[attr-defined]
        image_bytes = await download(object_key=asset.object_key)
        result = await self.warning_light_classifier.classify(
            image_bytes=image_bytes, candidate_codes=candidate_codes
        )
        # Filter to confident-enough labels for the LLM-facing summary,
        # but persist the full top-K for the audit record.
        top_codes = [p.code for p in result.predictions]
        taxonomy_lookup = await self.warning_light_taxonomy.lookup_by_codes(top_codes)

        predictions_payload = [
            {"code": p.code, "confidence": p.confidence} for p in result.predictions
        ]
        prediction_row = await self.warning_light_predictions.create(
            session_id=sess.id,
            user_id=user_id,
            media_asset_id=asset.id,
            model=result.model,
            predictions=predictions_payload,
            top_code=result.top_code,
        )

        # Classifier is self-hosted → no marginal API cost (compute is
        # fixed per the EC2/Lambda budget). Log a zero-spend row anyway
        # so the daily-spend dashboard accounts for the call volume.
        await self.spend.record(
            user_id=user_id,
            session_id=sess.id,
            model=result.model,
            prompt_tokens=0,
            completion_tokens=0,
            est_cost_micro_mnt=0,
        )

        confident_labels: list[dict[str, Any]] = []
        for p in result.predictions:
            if p.confidence < WARNING_LIGHT_CONFIDENCE_FLOOR:
                continue
            tax = taxonomy_lookup.get(p.code)
            confident_labels.append(
                {
                    "code": p.code,
                    "confidence": p.confidence,
                    "display_en": tax.display_en if tax is not None else None,
                    "display_mn": tax.display_mn if tax is not None else None,
                    "severity": tax.severity.value if tax is not None else None,
                }
            )

        if confident_labels:
            summary_lines = [
                "[warning-light scan] Detected dashboard icons (top-K, confidence ≥ 0.20):",
            ]
            for label in confident_labels:
                display = label["display_en"] or label["code"]
                summary_lines.append(
                    f"- {display} ({label['code']}, severity={label['severity']}, "
                    f"confidence={label['confidence']:.2f})"
                )
            summary_lines.append("Diagnose the most likely cause and recommend next steps.")
        else:
            summary_lines = [
                "[warning-light scan] Classifier returned no confident labels.",
                "Ask the driver to retake the photo with better lighting.",
            ]
        prompt_text = "\n".join(summary_lines)

        agent_reply = await self._dispatch_agent(session=sess, user_id=user_id, content=prompt_text)
        logger.info(
            "ai_warning_light_classified",
            session_id=str(sess.id),
            prediction_id=str(prediction_row.id),
            top_code=result.top_code,
            confident_count=len(confident_labels),
        )
        return WarningLightReply(
            prediction=prediction_row,
            labels=confident_labels,
            user_message=agent_reply.user_message,
            assistant_message=agent_reply.assistant_message,
            prompt_tokens=agent_reply.prompt_tokens,
            completion_tokens=agent_reply.completion_tokens,
            classifier_micro_mnt=0,
            agent_micro_mnt=agent_reply.est_cost_micro_mnt,
        )

    async def post_visual_message(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: VisualMessageCreateIn,
    ) -> MultimodalReply:
        """Open-vocab visual Q&A: image + prompt → Gemini multimodal → agent."""
        return await self._post_multimodal(
            session_id=session_id,
            user_id=user_id,
            asset_id=payload.media_asset_id,
            prompt=payload.prompt,
            kind=AiMultimodalKind.visual,
            allowed_purposes={
                MediaAssetPurpose.part_search,
                MediaAssetPurpose.review,
                MediaAssetPurpose.story,
            },
        )

    async def post_engine_sound_message(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: EngineSoundMessageCreateIn,
    ) -> MultimodalReply:
        """Engine-sound diagnosis. Whisper is wrong for non-speech audio."""
        prompt = (payload.prompt or "").strip() or ENGINE_SOUND_DEFAULT_PROMPT
        return await self._post_multimodal(
            session_id=session_id,
            user_id=user_id,
            asset_id=payload.media_asset_id,
            prompt=prompt,
            kind=AiMultimodalKind.engine_sound,
            allowed_purposes={MediaAssetPurpose.engine_sound},
        )

    async def _post_multimodal(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        asset_id: uuid.UUID,
        prompt: str,
        kind: AiMultimodalKind,
        allowed_purposes: set[MediaAssetPurpose],
    ) -> MultimodalReply:
        if self.multimodal is None or self.media_download is None:
            raise ConflictError("Multimodal AI is not configured")

        sess = await self.get_session_for_user(session_id=session_id, user_id=user_id)
        await self.rate_limiter.check_and_consume(user_id=user_id)

        asset = await self.session.get(MediaAsset, asset_id)
        if asset is None or asset.owner_id != user_id:
            raise NotFoundError("Asset not found")
        if asset.purpose not in allowed_purposes:
            raise ConflictError(
                f"Asset purpose '{asset.purpose.value}' not allowed for {kind.value}"
            )
        if asset.status != MediaAssetStatus.active:
            raise ConflictError("Asset is not active; confirm the upload first")

        download = self.media_download.download_bytes  # type: ignore[attr-defined]
        payload_bytes = await download(object_key=asset.object_key)

        if kind == AiMultimodalKind.visual:
            mm = await self.multimodal.visual(
                prompt=prompt,
                image_bytes=payload_bytes,
                image_mime=asset.content_type,
            )
            model_label = VISUAL_MODEL
            audio_seconds = 0
        else:
            mm = await self.multimodal.audio(
                prompt=prompt,
                audio_bytes=payload_bytes,
                audio_mime=asset.content_type,
            )
            model_label = AUDIO_MODEL
            # Multimodal audio cost approximates duration from byte size
            # at 16kbps until LiteLLM exposes provider-side duration. A
            # mid-2026 follow-up swaps this for the real number once
            # Gemini surfaces it.
            audio_seconds = max(1, len(payload_bytes) // 2_000)

        if not mm.text.strip():
            raise ConflictError("Multimodal model returned an empty response")

        call_row = await self.multimodal_calls.create(
            session_id=sess.id,
            user_id=user_id,
            media_asset_id=asset.id,
            kind=kind,
            model=model_label,
            prompt=prompt,
            response=mm.text,
            prompt_tokens=mm.prompt_tokens,
            completion_tokens=mm.completion_tokens,
            audio_seconds=audio_seconds,
        )
        cost = estimate_cost_micro_mnt(
            model=model_label,
            prompt_tokens=mm.prompt_tokens,
            completion_tokens=mm.completion_tokens,
            audio_seconds=audio_seconds,
        )
        await self.spend.record(
            user_id=user_id,
            session_id=sess.id,
            model=model_label,
            prompt_tokens=mm.prompt_tokens,
            completion_tokens=mm.completion_tokens,
            audio_seconds=audio_seconds,
            est_cost_micro_mnt=cost,
        )

        # Hand the multimodal model's response to the agent loop as a
        # synthesised user turn so it can ground its diagnosis (or
        # follow up via tools) instead of replacing the whole flow.
        if kind == AiMultimodalKind.visual:
            wrapped = (
                "[visual analysis]\n"
                f"Prompt: {prompt}\n"
                f"Vision model response: {mm.text}\n"
                "Diagnose, recommend repairs, and search parts as needed."
            )
        else:
            wrapped = (
                "[engine-sound analysis]\n"
                f"Audio model response: {mm.text}\n"
                "Diagnose the most likely fault and recommend next steps."
            )
        agent_reply = await self._dispatch_agent(session=sess, user_id=user_id, content=wrapped)
        logger.info(
            "ai_multimodal_call",
            session_id=str(sess.id),
            call_id=str(call_row.id),
            kind=kind.value,
            multimodal_micro_mnt=cost,
        )
        return MultimodalReply(
            call=call_row,
            user_message=agent_reply.user_message,
            assistant_message=agent_reply.assistant_message,
            prompt_tokens=agent_reply.prompt_tokens,
            completion_tokens=agent_reply.completion_tokens,
            multimodal_micro_mnt=cost,
            agent_micro_mnt=agent_reply.est_cost_micro_mnt,
        )
