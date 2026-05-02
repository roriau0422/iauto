"""Media platform — uploaded blob lifecycle on top of S3-compatible storage.

Per ARCHITECTURE.md and the user's session-6 directive: MinIO is the rail in
both dev and prod, addressed via the standard S3 API (boto3 + endpoint_url).

Flow:
    1. Client requests an upload slot — `POST /v1/media/uploads`.
    2. Backend creates a `media_assets` row in `pending` state, returns a
       presigned PUT URL bound to the object key the row owns.
    3. Client PUTs the bytes directly to MinIO.
    4. Client confirms — `POST /v1/media/uploads/{id}/confirm`. Backend
       HEADs the object, fills `byte_size`, flips status to `active`.
    5. Marketplace surfaces (search, quote, review) reference the asset
       by id; service code refuses non-active assets.
"""
