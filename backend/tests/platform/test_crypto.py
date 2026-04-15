"""Tests for `app.platform.crypto`."""

from __future__ import annotations

import secrets

import pytest
from cryptography.fernet import Fernet

from app.platform.crypto import (
    CryptoConfigError,
    CryptoDecryptError,
    DataCipher,
    SearchIndex,
)

# ---------------------------------------------------------------------------
# DataCipher
# ---------------------------------------------------------------------------


def _fresh_data_key() -> str:
    return Fernet.generate_key().decode()


def _fresh_search_key() -> str:
    return secrets.token_hex(32)


def test_data_cipher_round_trip() -> None:
    cipher = DataCipher(_fresh_data_key())
    assert cipher.decrypt(cipher.encrypt("+97688110921")) == "+97688110921"


def test_data_cipher_round_trip_cyrillic() -> None:
    cipher = DataCipher(_fresh_data_key())
    assert cipher.decrypt(cipher.encrypt("Хар")) == "Хар"


def test_data_cipher_is_non_deterministic() -> None:
    """Two encryptions of the same plaintext must differ.

    Fernet embeds a random IV per token; if we accidentally swapped it for
    a deterministic cipher this assertion would fire.
    """
    cipher = DataCipher(_fresh_data_key())
    a = cipher.encrypt("+97688110921")
    b = cipher.encrypt("+97688110921")
    assert a != b


def test_data_cipher_wrong_key_fails() -> None:
    cipher_a = DataCipher(_fresh_data_key())
    cipher_b = DataCipher(_fresh_data_key())
    token = cipher_a.encrypt("secret")
    with pytest.raises(CryptoDecryptError):
        cipher_b.decrypt(token)


def test_data_cipher_rejects_tampered_ciphertext() -> None:
    cipher = DataCipher(_fresh_data_key())
    token = bytearray(cipher.encrypt("secret"))
    # Flip a byte near the middle of the payload.
    token[len(token) // 2] ^= 0x01
    with pytest.raises(CryptoDecryptError):
        cipher.decrypt(bytes(token))


def test_data_cipher_empty_key_raises() -> None:
    with pytest.raises(CryptoConfigError):
        DataCipher("")


def test_data_cipher_malformed_key_raises() -> None:
    with pytest.raises(CryptoConfigError):
        DataCipher("not-a-valid-fernet-key")


def test_data_cipher_encrypt_rejects_bytes() -> None:
    cipher = DataCipher(_fresh_data_key())
    with pytest.raises(TypeError):
        cipher.encrypt(b"already bytes")  # type: ignore[arg-type]


def test_data_cipher_decrypt_rejects_str() -> None:
    cipher = DataCipher(_fresh_data_key())
    with pytest.raises(TypeError):
        cipher.decrypt("not bytes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SearchIndex
# ---------------------------------------------------------------------------


def test_search_index_is_deterministic() -> None:
    idx = SearchIndex(_fresh_search_key())
    h1 = idx.compute("+97688110921")
    h2 = idx.compute("+97688110921")
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_search_index_different_keys_yield_different_hashes() -> None:
    idx_a = SearchIndex(_fresh_search_key())
    idx_b = SearchIndex(_fresh_search_key())
    assert idx_a.compute("+97688110921") != idx_b.compute("+97688110921")


def test_search_index_different_inputs_yield_different_hashes() -> None:
    idx = SearchIndex(_fresh_search_key())
    assert idx.compute("+97688110921") != idx.compute("+97688110922")


def test_search_index_empty_key_raises() -> None:
    with pytest.raises(CryptoConfigError):
        SearchIndex("")


def test_search_index_malformed_hex_raises() -> None:
    with pytest.raises(CryptoConfigError):
        SearchIndex("zz" * 32)  # valid length, invalid hex chars


def test_search_index_too_short_raises() -> None:
    with pytest.raises(CryptoConfigError):
        SearchIndex("aabb" * 2)  # 8 bytes decoded — below min


def test_search_index_compute_rejects_bytes() -> None:
    idx = SearchIndex(_fresh_search_key())
    with pytest.raises(TypeError):
        idx.compute(b"bytes not allowed")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Cross-class properties
# ---------------------------------------------------------------------------


def test_search_index_is_not_reversible_by_cipher_key() -> None:
    """The search hash must not equal the Fernet ciphertext — sanity check."""
    data_key = _fresh_data_key()
    search_key = _fresh_search_key()
    cipher = DataCipher(data_key)
    idx = SearchIndex(search_key)
    plaintext = "+97688110921"
    token = cipher.encrypt(plaintext)
    h = idx.compute(plaintext)
    assert h.encode() != token  # obviously different encodings, but assert
