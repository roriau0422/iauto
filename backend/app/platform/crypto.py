"""Column-level encryption primitives: Fernet envelope + HMAC blind index.

The rest of the backend talks to two classes here:

* `DataCipher` — wraps `cryptography.fernet.Fernet`. Authenticated symmetric
  encryption (AES-128-CBC + HMAC-SHA256 internally), non-deterministic by
  design: encrypting the same plaintext twice yields two different
  ciphertexts. Use this to store PII we only ever need to read back whole,
  never to compare or join on.

* `SearchIndex` — deterministic HMAC-SHA256 fingerprint of the *normalized*
  plaintext. Same plaintext always yields the same 64-char hex string, so
  we can index it uniquely and run equality lookups (`WHERE
  phone_search = :h`) without decrypting every row.

Using two separate keys matters: a DB dump with the search column alone is
only useful against a precomputed dictionary of candidate plaintexts, and a
ciphertext dump without the data key is useless. Compromising one key does
not break the other.

Keys come from settings:

    APP_DATA_KEY    — Fernet URL-safe base64 (44 chars)
    APP_SEARCH_KEY  — HMAC-SHA256 key, hex-encoded (64 chars, 32 bytes)

Both are required. The app refuses to start if either is missing or
malformed; there are no ephemeral dev defaults, because dev keys that
silently rotate between runs produce undecryptable DB rows.
"""

from __future__ import annotations

import hmac
from functools import lru_cache
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken

from app.platform.config import Settings, get_settings


class CryptoConfigError(RuntimeError):
    """Raised at startup when encryption keys are missing or malformed."""


class CryptoDecryptError(RuntimeError):
    """Raised when ciphertext cannot be decrypted (tampered or wrong key)."""


# ---------------------------------------------------------------------------
# DataCipher — Fernet envelope
# ---------------------------------------------------------------------------


class DataCipher:
    """Envelope-encrypt text with a Fernet key from settings."""

    def __init__(self, key: str) -> None:
        if not key:
            raise CryptoConfigError(
                "APP_DATA_KEY is empty. Generate one with "
                "`python -c 'from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())'` and put it in .env."
            )
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise CryptoConfigError(f"APP_DATA_KEY is not a valid Fernet key: {exc}") from exc

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt a UTF-8 string. Returns ciphertext bytes.

        Fernet ciphertext is safe to store in a `bytea` column; we skip the
        base64 round-trip on the wire and store raw bytes for a slight space
        win. The token itself is non-deterministic (embedded random IV), so
        consecutive calls with the same plaintext return different bytes.
        """
        if not isinstance(plaintext, str):
            raise TypeError("DataCipher.encrypt requires str")
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        if not isinstance(ciphertext, bytes | bytearray | memoryview):
            raise TypeError("DataCipher.decrypt requires bytes-like input")
        try:
            plain_bytes = self._fernet.decrypt(bytes(ciphertext))
        except InvalidToken as exc:
            raise CryptoDecryptError(
                "Failed to decrypt ciphertext — wrong key, tampered data, "
                "or ciphertext written under a rotated key."
            ) from exc
        return plain_bytes.decode("utf-8")


# ---------------------------------------------------------------------------
# SearchIndex — HMAC-SHA256 blind index
# ---------------------------------------------------------------------------


class SearchIndex:
    """Deterministic HMAC-SHA256 fingerprint for equality lookups."""

    def __init__(self, key_hex: str) -> None:
        if not key_hex:
            raise CryptoConfigError(
                "APP_SEARCH_KEY is empty. Generate one with "
                "`python -c 'import secrets; print(secrets.token_hex(32))'` "
                "and put it in .env."
            )
        try:
            self._key = bytes.fromhex(key_hex)
        except ValueError as exc:
            raise CryptoConfigError(f"APP_SEARCH_KEY is not valid hex: {exc}") from exc
        if len(self._key) < 16:
            raise CryptoConfigError(
                f"APP_SEARCH_KEY must decode to at least 16 bytes "
                f"(got {len(self._key)}). Use `secrets.token_hex(32)`."
            )

    def compute(self, normalized: str) -> str:
        """Return the 64-char hex HMAC of the already-normalized plaintext.

        Callers MUST normalize the plaintext before calling (phone → E.164,
        VIN → upper+stripped, etc.). The search index does not normalize —
        that's domain knowledge the caller owns.
        """
        if not isinstance(normalized, str):
            raise TypeError("SearchIndex.compute requires str")
        return hmac.new(self._key, normalized.encode("utf-8"), sha256).hexdigest()


# ---------------------------------------------------------------------------
# Module-level singletons — built lazily from settings
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_cipher(settings: Settings | None = None) -> DataCipher:
    s = settings or get_settings()
    return DataCipher(s.app_data_key)


@lru_cache(maxsize=1)
def get_search_index(settings: Settings | None = None) -> SearchIndex:
    s = settings or get_settings()
    return SearchIndex(s.app_search_key)


def reset_crypto_caches() -> None:
    """Test-only: drop memoized ciphers so a test can rebuild them with
    different keys. Never call from production code."""
    get_cipher.cache_clear()
    get_search_index.cache_clear()
