"""HTTP + WebSocket routes for the chat context."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.dependencies import get_businesses_service
from app.businesses.service import BusinessesService
from app.chat.dependencies import get_chat_service
from app.chat.models import ChatMessageKind
from app.chat.pubsub import channel_for
from app.chat.schemas import (
    ChatMessageCreateIn,
    ChatMessageListOut,
    ChatMessageOut,
    ChatThreadListOut,
    ChatThreadOut,
    WsErrorOut,
    WsSendIn,
    WsSubscribeIn,
)
from app.chat.service import ChatService
from app.identity.dependencies import get_current_user
from app.identity.models import User, UserRole
from app.identity.repository import UserRepository
from app.identity.security import decode_access_token
from app.media.client import S3MediaClient
from app.media.service import MediaService
from app.platform.cache import get_redis
from app.platform.config import get_settings
from app.platform.db import get_session_factory
from app.platform.errors import AuthError
from app.platform.logging import get_logger

logger = get_logger("app.chat.router")
router = APIRouter(tags=["chat"])


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------


@router.get(
    "/chat/threads",
    response_model=ChatThreadListOut,
    summary="List the caller's chat threads (driver or business)",
)
async def list_threads(
    service: Annotated[ChatService, Depends(get_chat_service)],
    user: Annotated[User, Depends(get_current_user)],
    businesses: Annotated[BusinessesService, Depends(get_businesses_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChatThreadListOut:
    if user.role == UserRole.business:
        business = await businesses.businesses.get_by_owner(user.id)
        if business is None:
            return ChatThreadListOut(items=[], total=0)
        result = await service.list_threads_for_business(
            business_id=business.id, limit=limit, offset=offset
        )
    else:
        result = await service.list_threads_for_driver(
            driver_id=user.id, limit=limit, offset=offset
        )
    return ChatThreadListOut(
        items=[ChatThreadOut.model_validate(t) for t in result.items],
        total=result.total,
    )


@router.get(
    "/chat/threads/{thread_id}",
    response_model=ChatThreadOut,
    summary="Read a single thread (party-gated)",
)
async def get_thread(
    thread_id: uuid.UUID,
    service: Annotated[ChatService, Depends(get_chat_service)],
    user: Annotated[User, Depends(get_current_user)],
    businesses: Annotated[BusinessesService, Depends(get_businesses_service)],
) -> ChatThreadOut:
    business_id = await _resolve_business_id(user, businesses)
    thread = await service.get_thread_for_party(
        thread_id=thread_id, user_id=user.id, business_id=business_id
    )
    return ChatThreadOut.model_validate(thread)


@router.get(
    "/chat/threads/{thread_id}/messages",
    response_model=ChatMessageListOut,
    summary="Paginated message history (newest first; before_id cursors backward)",
)
async def list_messages(
    thread_id: uuid.UUID,
    service: Annotated[ChatService, Depends(get_chat_service)],
    user: Annotated[User, Depends(get_current_user)],
    businesses: Annotated[BusinessesService, Depends(get_businesses_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ChatMessageListOut:
    business_id = await _resolve_business_id(user, businesses)
    thread = await service.get_thread_for_party(
        thread_id=thread_id, user_id=user.id, business_id=business_id
    )
    result = await service.list_messages(thread=thread, limit=limit, before_id=before_id)
    return ChatMessageListOut(
        items=[ChatMessageOut.model_validate(m) for m in result.items],
        has_more=result.has_more,
    )


@router.post(
    "/chat/threads/{thread_id}/messages",
    response_model=ChatMessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="Append a message to a thread",
)
async def post_message(
    thread_id: uuid.UUID,
    body: ChatMessageCreateIn,
    service: Annotated[ChatService, Depends(get_chat_service)],
    user: Annotated[User, Depends(get_current_user)],
    businesses: Annotated[BusinessesService, Depends(get_businesses_service)],
) -> ChatMessageOut:
    business_id = await _resolve_business_id(user, businesses)
    thread = await service.get_thread_for_party(
        thread_id=thread_id, user_id=user.id, business_id=business_id
    )
    message = await service.post_message(
        thread=thread,
        author_user_id=user.id,
        kind=ChatMessageKind(body.kind),
        body=body.body,
        media_asset_id=body.media_asset_id,
    )
    return ChatMessageOut.model_validate(message)


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@router.websocket("/chat/ws")
async def chat_websocket(
    websocket: WebSocket,
    token: Annotated[str | None, Query()] = None,
) -> None:
    """Live-delivery WebSocket. Auth via `?token=<access_jwt>` query param.

    Frame protocol (JSON):
      Inbound  → `{type: "subscribe", thread_id}`
                  `{type: "send", thread_id, kind, body?, media_asset_id?}`
      Outbound → `{type: "message", message: {...}}`
                  `{type: "error",   error_code, detail}`
    """
    if token is None:
        await websocket.close(code=4401)
        return
    settings = get_settings()
    try:
        claims = decode_access_token(token, settings)
    except AuthError:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    redis = get_redis()
    pubsub = redis.pubsub()
    forward_task: asyncio.Task[None] | None = None
    try:
        forward_task = asyncio.create_task(
            _forward_pubsub_to_ws(websocket=websocket, pubsub=pubsub)
        )
        while True:
            raw = await websocket.receive_text()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    WsErrorOut(error_code="bad_json", detail="invalid JSON").model_dump()
                )
                continue
            if not isinstance(parsed, dict):
                await websocket.send_json(
                    WsErrorOut(
                        error_code="bad_frame", detail="frame must be a JSON object"
                    ).model_dump()
                )
                continue
            frame_type = parsed.get("type")
            if frame_type == "subscribe":
                await _handle_subscribe(
                    websocket=websocket,
                    pubsub=pubsub,
                    parsed=parsed,
                    user_id=claims.sub,
                )
            elif frame_type == "send":
                await _handle_send(
                    websocket=websocket,
                    parsed=parsed,
                    user_id=claims.sub,
                )
            else:
                await websocket.send_json(
                    WsErrorOut(
                        error_code="unknown_type",
                        detail=f"unknown frame type: {frame_type}",
                    ).model_dump()
                )
    except WebSocketDisconnect:
        pass
    finally:
        if forward_task is not None:
            forward_task.cancel()
        # Best-effort close. If the pubsub conn is already torn down the
        # close() raises; we don't care because we're tearing the WS
        # down anyway. `aclose` is untyped on the redis-py stub; ignore
        # the no-untyped-call warning at the suppress site only.
        with contextlib.suppress(Exception):
            await pubsub.aclose()  # type: ignore[no-untyped-call]


async def _handle_subscribe(
    *,
    websocket: WebSocket,
    pubsub: Any,
    parsed: dict[str, Any],
    user_id: uuid.UUID,
) -> None:
    try:
        frame = WsSubscribeIn(**parsed)
    except PydanticValidationError as exc:
        await websocket.send_json(
            WsErrorOut(error_code="bad_subscribe", detail=str(exc)).model_dump()
        )
        return
    factory = get_session_factory()
    async with factory() as session:
        try:
            chat, business_id = await _resolve_chat_and_business(session=session, user_id=user_id)
            thread = await chat.get_thread_for_party(
                thread_id=frame.thread_id, user_id=user_id, business_id=business_id
            )
        except Exception as exc:
            await websocket.send_json(
                WsErrorOut(error_code="subscribe_denied", detail=str(exc)).model_dump()
            )
            return
        await pubsub.subscribe(channel_for(thread.id))


async def _handle_send(
    *,
    websocket: WebSocket,
    parsed: dict[str, Any],
    user_id: uuid.UUID,
) -> None:
    try:
        frame = WsSendIn(**parsed)
    except PydanticValidationError as exc:
        await websocket.send_json(WsErrorOut(error_code="bad_send", detail=str(exc)).model_dump())
        return
    if frame.kind == "text" and not frame.body:
        await websocket.send_json(
            WsErrorOut(error_code="bad_send", detail="text messages require body").model_dump()
        )
        return
    if frame.kind == "media" and frame.media_asset_id is None:
        await websocket.send_json(
            WsErrorOut(
                error_code="bad_send", detail="media messages require media_asset_id"
            ).model_dump()
        )
        return

    factory = get_session_factory()
    async with factory() as session:
        try:
            chat, business_id = await _resolve_chat_and_business(session=session, user_id=user_id)
            thread = await chat.get_thread_for_party(
                thread_id=frame.thread_id, user_id=user_id, business_id=business_id
            )
            await chat.post_message(
                thread=thread,
                author_user_id=user_id,
                kind=ChatMessageKind(frame.kind),
                body=frame.body,
                media_asset_id=frame.media_asset_id,
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            await websocket.send_json(
                WsErrorOut(error_code="send_failed", detail=str(exc)).model_dump()
            )


async def _forward_pubsub_to_ws(*, websocket: WebSocket, pubsub: Any) -> None:
    """Continuously poll Redis Pub/Sub and forward into the WebSocket."""
    try:
        async for raw in pubsub.listen():
            if raw is None or raw.get("type") != "message":
                continue
            data = raw.get("data")
            if isinstance(data, bytes):
                data = data.decode()
            try:
                payload = json.loads(data)
            except (TypeError, ValueError):
                continue
            await websocket.send_json(payload)
    except asyncio.CancelledError:
        return


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _resolve_business_id(user: User, businesses: BusinessesService) -> uuid.UUID | None:
    if user.role != UserRole.business:
        return None
    business = await businesses.businesses.get_by_owner(user.id)
    return business.id if business is not None else None


async def _resolve_chat_and_business(
    *, session: AsyncSession, user_id: uuid.UUID
) -> tuple[ChatService, uuid.UUID | None]:
    """Build a ChatService bound to `session` and resolve the user's business_id.

    Used by the WebSocket handlers — each WS frame opens a fresh
    DB transaction so a long-lived connection doesn't pin a Postgres
    connection. The same path is what FastAPI's `get_chat_service`
    dependency does for REST callers.
    """
    settings = get_settings()
    media = MediaService(
        session=session,
        client=S3MediaClient(settings),
        bucket=settings.s3_bucket_media,
    )
    chat = ChatService(session=session, redis=get_redis(), media_svc=media)

    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(user_id)
    business_id: uuid.UUID | None = None
    if user is not None and user.role == UserRole.business:
        businesses = BusinessesService(session=session)
        business = await businesses.businesses.get_by_owner(user.id)
        business_id = business.id if business is not None else None
    return chat, business_id
