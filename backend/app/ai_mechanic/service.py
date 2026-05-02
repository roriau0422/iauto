"""AI Mechanic service — sessions, messages, agent dispatch, KB ingestion."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_mechanic.agent import (
    AgentContext,
    AgentRunner,
    AgentRunResult,
)
from app.ai_mechanic.embeddings import EmbeddingClient, content_hash
from app.ai_mechanic.models import AiMessage, AiMessageRole, AiSession
from app.ai_mechanic.rate_limit import AiRateLimiter
from app.ai_mechanic.repository import (
    AiEmbeddingCacheRepository,
    AiKbRepository,
    AiMessageRepository,
    AiSessionRepository,
    AiSpendRepository,
)
from app.ai_mechanic.schemas import (
    KbDocumentCreateIn,
    MessageCreateIn,
    SessionCreateIn,
)
from app.ai_mechanic.spend import estimate_cost_micro_mnt
from app.platform.config import Settings
from app.platform.errors import NotFoundError
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


class AiMechanicService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        redis: Redis,
        runner: AgentRunner,
        embeddings: EmbeddingClient,
        settings: Settings,
    ) -> None:
        self.session = session
        self.runner = runner
        self.embeddings = embeddings
        self.settings = settings
        self.kb = AiKbRepository(session)
        self.cache = AiEmbeddingCacheRepository(session)
        self.sessions = AiSessionRepository(session)
        self.messages = AiMessageRepository(session)
        self.spend = AiSpendRepository(session)
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

        # Rate-limit before persisting anything — protects from a buggy
        # client looping on the endpoint.
        await self.rate_limiter.check_and_consume(user_id=user_id)

        user_msg = await self.messages.append(
            session_id=session_id,
            role=AiMessageRole.user,
            content=payload.content,
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
            vehicle_id=sess.vehicle_id,
            embedding_client=self.embeddings,
        )
        run: AgentRunResult = await self.runner.run(
            ctx=ctx, history=history, user_input=payload.content
        )

        assistant_msg = await self.messages.append(
            session_id=session_id,
            role=AiMessageRole.assistant,
            content=run.final_output,
        )

        # Persist tool calls as separate `tool` rows for the audit log.
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
