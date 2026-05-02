"""HTTP routes for the AI Mechanic context."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.ai_mechanic.dependencies import get_ai_mechanic_service
from app.ai_mechanic.schemas import (
    AssistantReplyOut,
    KbDocumentCreateIn,
    KbDocumentIngestedOut,
    KbDocumentOut,
    MessageCreateIn,
    MessageListOut,
    MessageOut,
    SessionCreateIn,
    SessionListOut,
    SessionOut,
    VoiceMessageCreateIn,
    VoiceReplyOut,
    VoiceTranscriptOut,
)
from app.ai_mechanic.service import AiMechanicService
from app.identity.dependencies import get_current_user
from app.identity.models import User, UserRole

router = APIRouter(tags=["ai_mechanic"])


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@router.post(
    "/ai-mechanic/sessions",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start an AI Mechanic conversation (optionally tied to a vehicle)",
)
async def create_session(
    body: SessionCreateIn,
    service: Annotated[AiMechanicService, Depends(get_ai_mechanic_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> SessionOut:
    sess = await service.create_session(user_id=user.id, payload=body)
    return SessionOut.model_validate(sess)


@router.get(
    "/ai-mechanic/sessions",
    response_model=SessionListOut,
    summary="List the caller's AI sessions, newest first",
)
async def list_sessions(
    service: Annotated[AiMechanicService, Depends(get_ai_mechanic_service)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SessionListOut:
    items, total = await service.list_sessions(user_id=user.id, limit=limit, offset=offset)
    return SessionListOut(items=[SessionOut.model_validate(s) for s in items], total=total)


@router.get(
    "/ai-mechanic/sessions/{session_id}",
    response_model=SessionOut,
    summary="Read an AI session (caller only)",
)
async def get_session(
    session_id: uuid.UUID,
    service: Annotated[AiMechanicService, Depends(get_ai_mechanic_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> SessionOut:
    sess = await service.get_session_for_user(session_id=session_id, user_id=user.id)
    return SessionOut.model_validate(sess)


@router.get(
    "/ai-mechanic/sessions/{session_id}/messages",
    response_model=MessageListOut,
    summary="Full message log for a session, oldest first",
)
async def list_messages(
    session_id: uuid.UUID,
    service: Annotated[AiMechanicService, Depends(get_ai_mechanic_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> MessageListOut:
    rows = await service.list_messages(session_id=session_id, user_id=user.id)
    return MessageListOut(items=[MessageOut.model_validate(m) for m in rows])


@router.post(
    "/ai-mechanic/sessions/{session_id}/messages",
    response_model=AssistantReplyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Send a user message; persist + run agent + return assistant reply",
)
async def post_message(
    session_id: uuid.UUID,
    body: MessageCreateIn,
    service: Annotated[AiMechanicService, Depends(get_ai_mechanic_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> AssistantReplyOut:
    reply = await service.post_user_message(session_id=session_id, user_id=user.id, payload=body)
    return AssistantReplyOut(
        user_message=MessageOut.model_validate(reply.user_message),
        assistant_message=MessageOut.model_validate(reply.assistant_message),
        prompt_tokens=reply.prompt_tokens,
        completion_tokens=reply.completion_tokens,
        est_cost_micro_mnt=reply.est_cost_micro_mnt,
    )


@router.post(
    "/ai-mechanic/sessions/{session_id}/voice",
    response_model=VoiceReplyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Voice → Whisper transcription → agent reply",
)
async def post_voice_message(
    session_id: uuid.UUID,
    body: VoiceMessageCreateIn,
    service: Annotated[AiMechanicService, Depends(get_ai_mechanic_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> VoiceReplyOut:
    reply = await service.post_voice_message(session_id=session_id, user_id=user.id, payload=body)
    return VoiceReplyOut(
        transcript=VoiceTranscriptOut.model_validate(reply.transcript),
        user_message=MessageOut.model_validate(reply.user_message),
        assistant_message=MessageOut.model_validate(reply.assistant_message),
        prompt_tokens=reply.prompt_tokens,
        completion_tokens=reply.completion_tokens,
        transcription_micro_mnt=reply.transcription_micro_mnt,
        agent_micro_mnt=reply.agent_micro_mnt,
    )


# ---------------------------------------------------------------------------
# Knowledge base ingestion (admin only)
# ---------------------------------------------------------------------------


@router.post(
    "/ai-mechanic/kb/documents",
    response_model=KbDocumentIngestedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: ingest a curated knowledge document; idempotent on body hash",
)
async def ingest_document(
    body: KbDocumentCreateIn,
    service: Annotated[AiMechanicService, Depends(get_ai_mechanic_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> KbDocumentIngestedOut:
    if user.role != UserRole.admin:
        from app.platform.errors import ForbiddenError

        raise ForbiddenError("Admin role required")
    result = await service.ingest_document(payload=body)
    # `ingest_document` returns the document_id whether it inserted or
    # found an existing one. Re-fetch through the service so the API
    # response carries the persisted shape.
    from sqlalchemy import select as sa_select

    from app.ai_mechanic.models import AiKbDocument

    fetched = await service.session.execute(
        sa_select(AiKbDocument).where(AiKbDocument.id == result.document_id)
    )
    document = fetched.scalar_one()
    return KbDocumentIngestedOut(
        document=KbDocumentOut.model_validate(document),
        chunks_added=result.chunks_added,
        embeddings_cached=result.embeddings_cached,
    )
