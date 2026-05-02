"""Story: posts, likes, comments, feed pagination, ownership gates."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.models import BusinessMemberRole
from app.businesses.schemas import BusinessCreateIn
from app.businesses.service import BusinessesService
from app.identity.models import User, UserRole
from app.media.service import MediaService
from app.platform.errors import ConflictError, ForbiddenError, NotFoundError
from app.platform.outbox import OutboxEvent
from app.story.schemas import StoryCommentCreateIn, StoryPostCreateIn
from app.story.service import StoryService
from tests.media.test_service import BUCKET, FakeMediaClient


@pytest.fixture
def businesses_service(db_session: AsyncSession) -> BusinessesService:
    return BusinessesService(session=db_session)


@pytest.fixture
def media_service(db_session: AsyncSession) -> MediaService:
    return MediaService(session=db_session, client=FakeMediaClient(), bucket=BUCKET)


@pytest.fixture
def story(db_session: AsyncSession, media_service: MediaService) -> StoryService:
    return StoryService(session=db_session, media_svc=media_service)


async def _make_business(
    *,
    db_session: AsyncSession,
    businesses_service: BusinessesService,
    owner_phone: str,
) -> tuple[User, uuid.UUID]:
    owner = User(phone=owner_phone, role=UserRole.business)
    db_session.add(owner)
    await db_session.flush()
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Shop")
    )
    return owner, business.id


async def _make_user(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------


async def test_publish_post_emits_event(
    story: StoryService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113001",
    )
    post = await story.publish_as_business(
        tenant_id=business_id,
        author_user_id=owner.id,
        payload=StoryPostCreateIn(body="Hello iAuto"),
    )
    assert post.tenant_id == business_id
    assert post.author_user_id == owner.id
    assert post.author_kind.value == "business"

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    published = [e for e in events if e.event_type == "story.post_published"]
    assert len(published) == 1


async def test_delete_post_author_or_owner(
    story: StoryService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113002",
    )
    # Add a manager and let them post.
    manager = await _make_user(db_session, "+97688113003")
    business = await businesses_service.businesses.get_by_id(business_id)
    assert business is not None
    await businesses_service.add_member(
        business=business,
        actor_role=BusinessMemberRole.owner,
        user_phone=manager.phone,
        role=BusinessMemberRole.manager,
    )

    post = await story.publish_as_business(
        tenant_id=business_id,
        author_user_id=manager.id,
        payload=StoryPostCreateIn(body="manager post"),
    )

    # Stranger driver can't delete.
    stranger = await _make_user(db_session, "+97688113004")
    with pytest.raises(ForbiddenError):
        await story.delete(post_id=post.id, actor_user_id=stranger.id)

    # Owner can delete a manager's post.
    await story.delete(post_id=post.id, actor_user_id=owner.id)
    with pytest.raises(NotFoundError):
        await story.get(post.id)


# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------


async def test_feed_paginates_newest_first(
    story: StoryService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113005",
    )
    for i in range(5):
        await story.publish_as_business(
            tenant_id=business_id,
            author_user_id=owner.id,
            payload=StoryPostCreateIn(body=f"post {i}"),
        )

    page1 = await story.list_feed(limit=3, before_id=None)
    assert len(page1.items) == 3
    assert page1.has_more is True

    page2 = await story.list_feed(limit=3, before_id=page1.items[-1].id)
    assert len(page2.items) == 2
    assert page2.has_more is False


# ---------------------------------------------------------------------------
# Likes
# ---------------------------------------------------------------------------


async def test_like_unlike_idempotent(
    story: StoryService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113006",
    )
    post = await story.publish_as_business(
        tenant_id=business_id,
        author_user_id=owner.id,
        payload=StoryPostCreateIn(body="like me"),
    )
    fan = await _make_user(db_session, "+97688113007")

    result = await story.like(post_id=post.id, user_id=fan.id)
    assert result.like_count == 1

    with pytest.raises(ConflictError):
        await story.like(post_id=post.id, user_id=fan.id)

    unlike = await story.unlike(post_id=post.id, user_id=fan.id)
    assert unlike.like_count == 0

    # Second unlike is a no-op (idempotent).
    unlike2 = await story.unlike(post_id=post.id, user_id=fan.id)
    assert unlike2.like_count == 0


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


async def test_comment_increments_counter(
    story: StoryService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113008",
    )
    post = await story.publish_as_business(
        tenant_id=business_id,
        author_user_id=owner.id,
        payload=StoryPostCreateIn(body="discuss"),
    )
    a = await _make_user(db_session, "+97688113009")
    await story.comment(
        post_id=post.id,
        author_user_id=a.id,
        payload=StoryCommentCreateIn(body="great post"),
    )
    refreshed = await story.get(post.id)
    assert refreshed.comment_count == 1


async def test_delete_comment_author_or_owner(
    story: StoryService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113010",
    )
    post = await story.publish_as_business(
        tenant_id=business_id,
        author_user_id=owner.id,
        payload=StoryPostCreateIn(body="moderation test"),
    )
    a = await _make_user(db_session, "+97688113011")
    b = await _make_user(db_session, "+97688113012")
    comment_a = await story.comment(
        post_id=post.id,
        author_user_id=a.id,
        payload=StoryCommentCreateIn(body="from A"),
    )
    comment_b = await story.comment(
        post_id=post.id,
        author_user_id=b.id,
        payload=StoryCommentCreateIn(body="from B"),
    )

    # B can't delete A's comment.
    with pytest.raises(ForbiddenError):
        await story.delete_comment(comment_id=comment_a.id, actor_user_id=b.id)

    # Author A can.
    await story.delete_comment(comment_id=comment_a.id, actor_user_id=a.id)

    # Owner can delete B's comment.
    await story.delete_comment(comment_id=comment_b.id, actor_user_id=owner.id)

    refreshed = await story.get(post.id)
    assert refreshed.comment_count == 0


async def test_list_comments_pages_with_before_id(
    story: StoryService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113013",
    )
    post = await story.publish_as_business(
        tenant_id=business_id,
        author_user_id=owner.id,
        payload=StoryPostCreateIn(body="paginate me"),
    )
    a = await _make_user(db_session, "+97688113014")
    for i in range(5):
        await story.comment(
            post_id=post.id,
            author_user_id=a.id,
            payload=StoryCommentCreateIn(body=f"c{i}"),
        )

    page1 = await story.list_comments(post_id=post.id, limit=3, before_id=None)
    assert len(page1.items) == 3
    assert page1.has_more is True
    page2 = await story.list_comments(post_id=post.id, limit=3, before_id=page1.items[-1].id)
    assert len(page2.items) == 2
    assert page2.has_more is False


# ---------------------------------------------------------------------------
# Driver-authored posts (session 23)
# ---------------------------------------------------------------------------


async def test_publish_as_driver_no_tenant(
    story: StoryService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_user(db_session, "+97688113101")
    post = await story.publish_as_driver(
        author_user_id=driver.id,
        payload=StoryPostCreateIn(body="Just bought a Prius!"),
    )
    assert post.tenant_id is None
    assert post.author_kind.value == "driver"
    assert post.author_user_id == driver.id

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    published = [e for e in events if e.event_type == "story.post_published"]
    assert len(published) == 1
    assert published[0].payload["author_kind"] == "driver"
    assert published[0].tenant_id is None


async def test_feed_mixes_driver_and_business_posts(
    story: StoryService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113102",
    )
    driver = await _make_user(db_session, "+97688113103")

    biz_post = await story.publish_as_business(
        tenant_id=business_id,
        author_user_id=owner.id,
        payload=StoryPostCreateIn(body="Sale on brake pads"),
    )
    drv_post = await story.publish_as_driver(
        author_user_id=driver.id,
        payload=StoryPostCreateIn(body="My new wheels"),
    )

    feed = await story.list_feed(limit=10, before_id=None)
    ids_in_feed = {p.id for p in feed.items}
    assert biz_post.id in ids_in_feed
    assert drv_post.id in ids_in_feed
    # Newest first by `(created_at, id) DESC`. The two posts are created
    # in the same transaction so they share `created_at` to sub-second
    # precision; the deterministic tie-break is by id descending.
    expected_first = drv_post.id if drv_post.id > biz_post.id else biz_post.id
    assert feed.items[0].id == expected_first


async def test_business_can_filter_to_own_posts_via_tenant_id(
    story: StoryService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    """Tenant isolation still works: filtering by tenant_id excludes other
    tenants' posts AND driver-personal posts.
    """
    owner_a, business_a = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113104",
    )
    owner_b, business_b = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113105",
    )
    driver = await _make_user(db_session, "+97688113106")

    a_post = await story.publish_as_business(
        tenant_id=business_a,
        author_user_id=owner_a.id,
        payload=StoryPostCreateIn(body="A"),
    )
    await story.publish_as_business(
        tenant_id=business_b,
        author_user_id=owner_b.id,
        payload=StoryPostCreateIn(body="B"),
    )
    await story.publish_as_driver(
        author_user_id=driver.id,
        payload=StoryPostCreateIn(body="D"),
    )

    rows, _ = await story.posts.list_for_tenant(tenant_id=business_a, limit=10, before_id=None)
    assert [p.id for p in rows] == [a_post.id]


async def test_driver_post_only_author_can_delete(
    story: StoryService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_user(db_session, "+97688113107")
    stranger = await _make_user(db_session, "+97688113108")
    post = await story.publish_as_driver(
        author_user_id=driver.id,
        payload=StoryPostCreateIn(body="personal"),
    )
    with pytest.raises(ForbiddenError):
        await story.delete(post_id=post.id, actor_user_id=stranger.id)
    await story.delete(post_id=post.id, actor_user_id=driver.id)
    with pytest.raises(NotFoundError):
        await story.get(post.id)
