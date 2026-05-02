"""Database access for the AI Mechanic context.

Vector-typed columns (`embedding vector(1536)`) are read/written via
raw SQL — pgvector ships with SQLAlchemy compat helpers, but pulling
in an extra dep just for two columns isn't worth it. The raw SQL is
narrow and obvious.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_mechanic.models import (
    AiKbDocument,
    AiMessage,
    AiMessageRole,
    AiSession,
    AiSessionStatus,
    AiSpendEvent,
)


def _vector_literal(vec: list[float]) -> str:
    """pgvector wire format: `[0.1,0.2,...]`. Joined as plain SQL text."""
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


class AiKbRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_document_by_hash(self, content_hash: str) -> AiKbDocument | None:
        stmt = select(AiKbDocument).where(AiKbDocument.content_hash == content_hash)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create_document(
        self,
        *,
        title: str,
        body: str,
        content_hash: str,
        source_url: str | None,
        language: str,
        vehicle_brand_id: uuid.UUID | None,
        vehicle_model_id: uuid.UUID | None,
    ) -> AiKbDocument:
        doc = AiKbDocument(
            title=title,
            body=body,
            content_hash=content_hash,
            source_url=source_url,
            language=language,
            vehicle_brand_id=vehicle_brand_id,
            vehicle_model_id=vehicle_model_id,
        )
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def insert_chunk(
        self,
        *,
        document_id: uuid.UUID,
        chunk_index: int,
        body: str,
        embedding: list[float],
    ) -> uuid.UUID:
        chunk_id = uuid.uuid4()
        await self.session.execute(
            text(
                """
                INSERT INTO ai_kb_chunks (id, document_id, chunk_index, body, embedding)
                VALUES (:id, :doc, :idx, :body, CAST(:emb AS vector))
                """
            ),
            {
                "id": chunk_id,
                "doc": document_id,
                "idx": chunk_index,
                "body": body,
                "emb": _vector_literal(embedding),
            },
        )
        return chunk_id

    async def search_chunks(
        self,
        *,
        embedding: list[float],
        limit: int,
        vehicle_brand_id: uuid.UUID | None = None,
    ) -> list[tuple[uuid.UUID, str, str, float]]:
        """Return `(chunk_id, document_title, body, distance)` sorted by cosine.

        `distance` is `embedding <=> :q` in pgvector terms (cosine distance,
        smaller is closer). Brand-scoped retrieval prefers documents
        anchored to the vehicle's brand when set, but never excludes
        unanchored generic ones — they bubble up at the bottom.
        """
        params: dict[str, Any] = {
            "q": _vector_literal(embedding),
            "limit": limit,
        }
        # Brand filter is optional — we always return results, just
        # boost matches.
        brand_filter = ""
        if vehicle_brand_id is not None:
            brand_filter = "AND (d.vehicle_brand_id = :brand OR d.vehicle_brand_id IS NULL)"
            params["brand"] = vehicle_brand_id

        # `brand_filter` is a hand-curated literal selected above — never
        # user input — so the f-string interpolation is safe. Bandit
        # can't see that, so suppress S608 at the call site.
        sql = f"""
            SELECT c.id, d.title, c.body,
                   (c.embedding <=> CAST(:q AS vector)) AS distance
            FROM ai_kb_chunks c
            JOIN ai_kb_documents d ON d.id = c.document_id
            WHERE c.embedding IS NOT NULL {brand_filter}
            ORDER BY c.embedding <=> CAST(:q AS vector)
            LIMIT :limit
        """  # noqa: S608
        result = await self.session.execute(text(sql), params)
        return [(row[0], row[1], row[2], float(row[3])) for row in result.fetchall()]


class AiEmbeddingCacheRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, *, scope_kind: str, scope_id: uuid.UUID | None, content_hash: str
    ) -> list[float] | None:
        result = await self.session.execute(
            text(
                """
                SELECT embedding::text
                FROM ai_embedding_cache
                WHERE scope_kind = :kind
                  AND content_hash = :hash
                  AND (scope_id = :sid OR (scope_id IS NULL AND :sid IS NULL))
                LIMIT 1
                """
            ),
            {"kind": scope_kind, "hash": content_hash, "sid": scope_id},
        )
        row = result.first()
        if row is None:
            return None
        # pgvector text form is `[0.1,0.2,...]`. Strip + split.
        raw = row[0]
        return [float(x) for x in raw.strip("[]").split(",")]

    async def put(
        self,
        *,
        scope_kind: str,
        scope_id: uuid.UUID | None,
        content_hash: str,
        embedding: list[float],
    ) -> None:
        await self.session.execute(
            text(
                """
                INSERT INTO ai_embedding_cache
                    (id, scope_kind, scope_id, content_hash, embedding)
                VALUES (:id, :kind, :sid, :hash, CAST(:emb AS vector))
                ON CONFLICT (scope_kind, scope_id, content_hash) DO NOTHING
                """
            ),
            {
                "id": uuid.uuid4(),
                "kind": scope_kind,
                "sid": scope_id,
                "hash": content_hash,
                "emb": _vector_literal(embedding),
            },
        )


class AiSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_user(self, *, session_id: uuid.UUID, user_id: uuid.UUID) -> AiSession | None:
        sess = await self.session.get(AiSession, session_id)
        if sess is None or sess.user_id != user_id:
            return None
        return sess

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        vehicle_id: uuid.UUID | None,
        title: str | None,
    ) -> AiSession:
        sess = AiSession(
            user_id=user_id,
            vehicle_id=vehicle_id,
            title=title,
            status=AiSessionStatus.active,
        )
        self.session.add(sess)
        await self.session.flush()
        return sess

    async def list_for_user(
        self, *, user_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[AiSession], int]:
        base = select(AiSession).where(AiSession.user_id == user_id)
        stmt = base.order_by(AiSession.created_at.desc()).limit(limit).offset(offset)
        count_stmt = select(func.count(AiSession.id)).where(AiSession.user_id == user_id)
        rows = list((await self.session.execute(stmt)).scalars())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total


class AiMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        *,
        session_id: uuid.UUID,
        role: AiMessageRole,
        content: str,
        tool_name: str | None = None,
        tool_payload: dict[str, Any] | None = None,
    ) -> AiMessage:
        message = AiMessage(
            session_id=session_id,
            role=role,
            content=content,
            tool_name=tool_name,
            tool_payload=tool_payload,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_for_session(self, *, session_id: uuid.UUID) -> list[AiMessage]:
        stmt = (
            select(AiMessage)
            .where(AiMessage.session_id == session_id)
            .order_by(AiMessage.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars())


class AiSpendRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID | None,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        est_cost_micro_mnt: int,
    ) -> AiSpendEvent:
        event = AiSpendEvent(
            user_id=user_id,
            session_id=session_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            est_cost_micro_mnt=est_cost_micro_mnt,
        )
        self.session.add(event)
        await self.session.flush()
        return event
