"""DB-backed tests for the encrypted `User.phone` property.

These assertions exercise the full write → DB → read round-trip so we catch
any SA 2.0 regression where the Python `@property` might stop routing
through the encryption helpers.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User, UserRole
from app.identity.repository import UserRepository
from app.platform.crypto import get_search_index


async def test_user_phone_round_trip_through_db(
    db_session: AsyncSession,
) -> None:
    user = User(phone="+97688110000", role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()

    # Clear SA's identity map so the next read materializes from DB state.
    db_session.expunge_all()

    reloaded = await db_session.get(User, user.id)
    assert reloaded is not None
    assert reloaded.phone == "+97688110000"
    assert isinstance(reloaded.phone_cipher, bytes | memoryview)
    assert isinstance(reloaded.phone_search, str)
    assert len(reloaded.phone_search) == 64


async def test_user_plaintext_column_is_gone(
    db_session: AsyncSession,
) -> None:
    """Post-migration, there must not be a `users.phone` column."""
    result = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'phone'"
        )
    )
    assert result.first() is None


async def test_phone_search_is_deterministic_for_same_input(
    db_session: AsyncSession,
) -> None:
    u1 = User(phone="+97688110001", role=UserRole.driver)
    u2 = User(phone="88110002", role=UserRole.driver)
    db_session.add_all([u1, u2])
    await db_session.flush()

    # `88110002` should normalize to `+97688110002` first; the search key
    # must therefore match what the direct-E.164 caller would compute.
    expected_u2 = get_search_index().compute("+97688110002")
    assert u2.phone_search == expected_u2
    # And obviously different phones get different hashes.
    assert u1.phone_search != u2.phone_search


async def test_duplicate_phone_triggers_unique_violation(
    db_session: AsyncSession,
) -> None:
    db_session.add(User(phone="+97688110003", role=UserRole.driver))
    await db_session.flush()

    # A second user with the same normalized phone must collide on
    # `uq_users_phone_search`. Wrap in a savepoint so the outer fixture
    # transaction stays usable after the rollback from IntegrityError.
    async def _flush_dup() -> None:
        async with db_session.begin_nested():
            db_session.add(User(phone="+97688110003", role=UserRole.driver))
            await db_session.flush()

    with pytest.raises(IntegrityError):
        await _flush_dup()


async def test_repository_get_by_phone_uses_search_index(
    db_session: AsyncSession,
) -> None:
    original = User(phone="+97688110004", role=UserRole.driver)
    db_session.add(original)
    await db_session.flush()

    repo = UserRepository(db_session)
    found = await repo.get_by_phone("+97688110004")
    assert found is not None
    assert found.id == original.id

    # Normalization path — caller passes the national form.
    found_via_national = await repo.get_by_phone("88110004")
    assert found_via_national is not None
    assert found_via_national.id == original.id


async def test_phone_cipher_is_non_deterministic(
    db_session: AsyncSession,
) -> None:
    """Two users with the same phone can't coexist (UNIQUE), but two
    *encryptions* of the same plaintext must differ — verify by comparing
    the cipher of one user against a reinstantiated cipher for the same
    plaintext held in-memory only."""
    u1 = User(phone="+97688110005", role=UserRole.driver)
    u2 = User(phone="+97688110005", role=UserRole.driver)
    # Both objects are in-memory only, neither is flushed — they can share
    # the normalized search hash but MUST differ in their Fernet ciphertext.
    assert u1.phone_search == u2.phone_search
    assert u1.phone_cipher != u2.phone_cipher
