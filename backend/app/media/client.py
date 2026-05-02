"""S3-compatible client (used against MinIO in dev + prod).

`boto3` is sync-only at the API surface. We wrap each call in
`asyncio.to_thread` so it doesn't block the event loop. Presign and HEAD
are fast enough that this is a non-issue in practice — and avoids dragging
`aioboto3` and its session lifecycle into the FastAPI lifespan.

Path-style addressing is forced because MinIO does not implement
virtual-host-style by default.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.platform.config import Settings

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Tunables
# ----------------------------------------------------------------------------

# Max bytes a client may upload via a single presigned PUT. 10 MiB is enough
# for review photos and part-search images at consumer-camera resolutions.
PUT_MAX_BYTES: int = 10 * 1024 * 1024

# How long a presigned URL stays valid. Balanced: long enough for a slow
# mobile network to finish the PUT, short enough that a leaked URL stops
# being useful within a minute.
PUT_TTL_SECONDS: int = 60
GET_TTL_SECONDS: int = 300


class MediaClient(Protocol):
    """Surface the rest of the codebase consumes.

    Defined as a Protocol so tests can substitute a fake without subclassing.
    """

    async def presign_put(
        self,
        *,
        object_key: str,
        content_type: str,
        max_bytes: int,
    ) -> str: ...

    async def presign_get(self, *, object_key: str) -> str: ...

    async def head_object(self, *, object_key: str) -> dict[str, Any] | None: ...

    async def download_bytes(self, *, object_key: str) -> bytes: ...

    async def delete_object(self, *, object_key: str) -> None: ...


class S3MediaClient:
    """Concrete `MediaClient` backed by `boto3` against an S3-compatible host."""

    def __init__(self, settings: Settings) -> None:
        endpoint = str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None
        # SigV4 + path-style — MinIO requires both, AWS supports both.
        cfg = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if settings.s3_use_path_style else "virtual"},
        )
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
            region_name=settings.s3_region,
            config=cfg,
        )
        self._bucket = settings.s3_bucket_media

    @property
    def bucket(self) -> str:
        return self._bucket

    async def presign_put(
        self,
        *,
        object_key: str,
        content_type: str,
        max_bytes: int,
    ) -> str:
        """Return a presigned PUT URL the client can upload directly to.

        The returned URL is bound to the bucket, key, and content-type. The
        client must send `Content-Type: <content_type>` on the PUT or the
        signature check fails.

        boto3 signs `Content-Length-Range` for POST policies but not for
        plain PUT. We rely on the confirm-step HEAD to enforce the cap
        (`max_bytes` is checked against the response `ContentLength`).
        """
        # Bind args via `params` — the client's signer hashes them into URL.
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            ClientMethod="put_object",
            Params={
                "Bucket": self._bucket,
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=PUT_TTL_SECONDS,
            HttpMethod="PUT",
        )

    async def presign_get(self, *, object_key: str) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            ClientMethod="get_object",
            Params={"Bucket": self._bucket, "Key": object_key},
            ExpiresIn=GET_TTL_SECONDS,
            HttpMethod="GET",
        )

    async def head_object(self, *, object_key: str) -> dict[str, Any] | None:
        """Return HEAD metadata or None if the object is missing.

        boto3 raises `ClientError` with code `404` for a missing object;
        we collapse that to None so callers get a clean "is it there"
        signal without catching botocore exceptions themselves.
        """

        def _head() -> dict[str, Any]:
            # The lambda dance keeps boto3-stubs happy — `to_thread`'s
            # ParamSpec can't forward boto3's `**HeadObjectRequestTypeDef`
            # **kwargs partial-application directly. Cast to plain dict so
            # callers don't depend on the TypedDict surface.
            return dict(self._client.head_object(Bucket=self._bucket, Key=object_key))

        try:
            return await asyncio.to_thread(_head)
        except ClientError as exc:
            err_code = exc.response.get("Error", {}).get("Code")
            if err_code in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    async def download_bytes(self, *, object_key: str) -> bytes:
        """Pull the full object body. Used server-side for AI ingestion.

        Whisper transcription needs the audio bytes inline — presigned
        GET URLs aren't useful when the consumer is the same backend.
        boto3's `get_object` returns a streaming body; we read it all
        because Whisper accepts a single payload, not a stream.
        """

        def _get() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
            body = response["Body"]
            try:
                return bytes(body.read())
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()

        return await asyncio.to_thread(_get)

    async def delete_object(self, *, object_key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object,
            Bucket=self._bucket,
            Key=object_key,
        )
