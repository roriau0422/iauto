"""Agent definition + tool wiring + runner abstraction.

Built on the OpenAI Agents SDK (v0.7+). Gemini routes via the LiteLLM
extension — `LitellmModel(model="gemini/gemini-3-flash-preview", api_key=...)`.

Tools take `RunContextWrapper[AgentContext]` so they can reach into the
DB session + the calling user's vehicle id without the LLM having to
provide them. The LLM never owns source-of-truth (arch §13 decision 4)
— every tool calls back into the deterministic spine.

Tests substitute a `FakeAgentRunner` that records the tool calls and
returns canned assistant replies, so CI never burns tokens. The live
runner is exercised behind the `AI_LIVE_TESTS=1` env flag.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# `RunContextWrapper` must be available in the module globals — the
# `@function_tool` decorator resolves type hints via `typing.get_type_hints`,
# which looks them up in the function's `__globals__` (= this module),
# not the local namespace inside `build_live_runner`. Importing here also
# avoids a NameError at agent construction time on Python 3.13.
try:
    from agents import RunContextWrapper
except ImportError:  # pragma: no cover - tests stub the live runner
    RunContextWrapper = None  # type: ignore[assignment, misc]

from app.ai_mechanic.embeddings import EmbeddingClient, content_hash
from app.ai_mechanic.repository import AiEmbeddingCacheRepository, AiKbRepository
from app.marketplace.models import QuoteCondition
from app.platform.config import Settings
from app.platform.logging import get_logger
from app.vehicles.models import Vehicle, VehicleServiceLog
from app.warehouse.models import WarehouseSku

logger = get_logger("app.ai_mechanic.agent")


SYSTEM_INSTRUCTIONS = (
    "You are iAuto Mechanic, an expert assistant for Mongolian drivers. "
    "ALWAYS use the provided tools instead of guessing. "
    "Begin every diagnosis by calling get_vehicle_context. "
    "When suggesting parts, call search_parts; when explaining symptoms, "
    "call search_knowledge_base; when estimating cost, call estimate_labor_cost. "
    "Reply in Mongolian if the user wrote in Mongolian, otherwise in English. "
    "Be concise and decisive — drivers need an answer, not a textbook."
)


# Rough labor-cost rule table for the placeholder estimator. Real values
# land alongside the proper repair-catalog ingest in phase 4.
_LABOR_RULES_MNT: dict[str, int] = {
    "oil_change": 50_000,
    "brake_pads": 120_000,
    "battery_replacement": 80_000,
    "tire_rotation": 30_000,
    "diagnostic": 40_000,
}


@dataclass(slots=True)
class AgentContext:
    """Per-request injected context the tools read.

    Everything here is locally scoped to the FastAPI request — never
    serialized into the LLM prompt. The Agents SDK calls our tool
    functions with `RunContextWrapper[AgentContext]`, which exposes
    `.context`.
    """

    session: AsyncSession
    user_id: uuid.UUID
    vehicle_id: uuid.UUID | None
    embedding_client: EmbeddingClient


@dataclass(slots=True)
class AgentRunResult:
    """What the agent returns after one user-message → assistant-reply pass.

    `tool_calls` is the structured list the service persists into the
    `ai_messages` log so the conversation history is auditable.
    """

    final_output: str
    prompt_tokens: int
    completion_tokens: int
    tool_calls: list[dict[str, Any]]


class AgentRunner(Protocol):
    """Surface the service uses; tests substitute `FakeAgentRunner`."""

    async def run(
        self,
        *,
        ctx: AgentContext,
        history: list[dict[str, str]],
        user_input: str,
    ) -> AgentRunResult: ...


# ---------------------------------------------------------------------------
# Tool implementations (called by the LLM via @function_tool)
# ---------------------------------------------------------------------------


async def get_vehicle_context_impl(ctx: AgentContext) -> dict[str, Any]:
    """Return basic facts + recent service-history about the active vehicle."""
    if ctx.vehicle_id is None:
        return {"vehicle": None, "service_history": []}
    vehicle = await ctx.session.get(Vehicle, ctx.vehicle_id)
    if vehicle is None:
        return {"vehicle": None, "service_history": []}

    history_stmt = (
        select(VehicleServiceLog)
        .where(VehicleServiceLog.vehicle_id == ctx.vehicle_id)
        .order_by(VehicleServiceLog.noted_at.desc())
        .limit(5)
    )
    rows = list((await ctx.session.execute(history_stmt)).scalars())

    return {
        "vehicle": {
            "id": str(vehicle.id),
            "make": vehicle.make,
            "model": vehicle.model,
            "build_year": vehicle.build_year,
            "fuel_type": vehicle.fuel_type,
            "steering_side": vehicle.steering_side.value
            if vehicle.steering_side is not None
            else None,
            "capacity_cc": vehicle.capacity_cc,
        },
        "service_history": [
            {
                "kind": log.kind.value,
                "noted_at": log.noted_at.isoformat(),
                "title": log.title,
                "mileage_km": log.mileage_km,
                "cost_mnt": log.cost_mnt,
            }
            for log in rows
        ],
    }


async def search_knowledge_base_impl(
    ctx: AgentContext, query: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Embed the query, run cosine-ANN against ai_kb_chunks, return top-K."""
    if not query.strip():
        return []
    cache = AiEmbeddingCacheRepository(ctx.session)
    kb = AiKbRepository(ctx.session)

    # Cache lookup keyed on the raw query text (no vehicle scope here —
    # the query is global; vehicle scoping happens via the result filter
    # below).
    h = content_hash(query)
    cached = await cache.get(scope_kind="global", scope_id=None, content_hash=h)
    if cached is not None:
        embedding = cached
    else:
        embeddings = await ctx.embedding_client.embed(texts=[query])
        embedding = embeddings[0]
        await cache.put(
            scope_kind="global",
            scope_id=None,
            content_hash=h,
            embedding=embedding,
        )

    brand_id: uuid.UUID | None = None
    if ctx.vehicle_id is not None:
        vehicle = await ctx.session.get(Vehicle, ctx.vehicle_id)
        if vehicle is not None:
            brand_id = vehicle.vehicle_brand_id

    rows = await kb.search_chunks(embedding=embedding, limit=limit, vehicle_brand_id=brand_id)
    return [
        {
            "chunk_id": str(chunk_id),
            "title": title,
            "body": body,
            "distance": distance,
        }
        for chunk_id, title, body, distance in rows
    ]


async def search_parts_impl(ctx: AgentContext, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search SKUs across all businesses by display_name (trgm ILIKE)."""
    if not query.strip():
        return []
    pattern = f"%{query}%"
    stmt = select(WarehouseSku).where(WarehouseSku.display_name.ilike(pattern)).limit(limit)
    rows = list((await ctx.session.execute(stmt)).scalars())
    return [
        {
            "sku_id": str(sku.id),
            "tenant_id": str(sku.tenant_id),
            "sku_code": sku.sku_code,
            "display_name": sku.display_name,
            "condition": sku.condition.value
            if isinstance(sku.condition, QuoteCondition)
            else str(sku.condition),
            "unit_price_mnt": sku.unit_price_mnt,
        }
        for sku in rows
    ]


def estimate_labor_cost_impl(repair_kind: str) -> dict[str, Any]:
    """Placeholder rule table — phase 4 swaps in a real catalog-driven estimate."""
    key = repair_kind.strip().lower().replace(" ", "_")
    cost = _LABOR_RULES_MNT.get(key)
    return {
        "repair_kind": key,
        "estimated_labor_cost_mnt": cost,
        "is_known": cost is not None,
    }


# ---------------------------------------------------------------------------
# Live runner — wraps the OpenAI Agents SDK
# ---------------------------------------------------------------------------


def build_live_runner(*, settings: Settings) -> AgentRunner:
    """Construct the production Agents SDK runner.

    Lazy import the Agents SDK so the module loads without it (tests
    that only exercise the fake runner don't need the dep at import
    time).
    """
    # Agents SDK is heavy at import — load only when the live runner is
    # actually wired up.
    from agents import Agent, Runner, function_tool
    from agents.extensions.models.litellm_model import LitellmModel

    @function_tool
    async def get_vehicle_context(
        wrapper: RunContextWrapper[AgentContext],
    ) -> dict[str, Any]:
        """Return the active vehicle's facts + recent service history."""
        return await get_vehicle_context_impl(wrapper.context)

    @function_tool
    async def search_knowledge_base(
        wrapper: RunContextWrapper[AgentContext], query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Search the curated maintenance knowledge base by semantic similarity."""
        return await search_knowledge_base_impl(wrapper.context, query, limit)

    @function_tool
    async def search_parts(
        wrapper: RunContextWrapper[AgentContext], query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search the marketplace catalog of parts (SKUs) by display name."""
        return await search_parts_impl(wrapper.context, query, limit)

    @function_tool
    def estimate_labor_cost(repair_kind: str) -> dict[str, Any]:
        """Return a rough labor-cost estimate for a common repair kind in MNT."""
        return estimate_labor_cost_impl(repair_kind)

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    model = LitellmModel(
        model=settings.ai_mechanic_model,
        api_key=settings.gemini_api_key,
    )
    agent = Agent[AgentContext](
        name="iAuto Mechanic",
        instructions=SYSTEM_INSTRUCTIONS,
        model=model,
        tools=[
            get_vehicle_context,
            search_knowledge_base,
            search_parts,
            estimate_labor_cost,
        ],
    )

    class _LiveRunner:
        async def run(
            self,
            *,
            ctx: AgentContext,
            history: list[dict[str, str]],
            user_input: str,
        ) -> AgentRunResult:
            # Agents SDK accepts a list of message dicts as input. We
            # concatenate prior history with the new user turn so the
            # LLM has full context.
            input_payload: list[dict[str, str]] = list(history)
            input_payload.append({"role": "user", "content": user_input})
            result = await Runner.run(
                starting_agent=agent,
                input=input_payload,  # type: ignore[arg-type]
                context=ctx,
            )
            # Token usage extraction — Agents SDK exposes per-turn usage
            # via `result.raw_responses`. We sum across turns. Fields may
            # vary by provider; fall back to 0 if the LiteLLM response
            # didn't surface them.
            prompt_tokens = 0
            completion_tokens = 0
            tool_calls: list[dict[str, Any]] = []
            for raw in getattr(result, "raw_responses", []) or []:
                usage = getattr(raw, "usage", None)
                if usage is not None:
                    prompt_tokens += int(getattr(usage, "input_tokens", 0) or 0)
                    completion_tokens += int(getattr(usage, "output_tokens", 0) or 0)
            for item in getattr(result, "new_items", []) or []:
                if getattr(item, "type", None) == "tool_call_item":
                    raw_item = getattr(item, "raw_item", None)
                    tool_calls.append(
                        {
                            "name": getattr(raw_item, "name", "unknown"),
                            "arguments": getattr(raw_item, "arguments", None),
                        }
                    )
            return AgentRunResult(
                final_output=str(result.final_output or ""),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                tool_calls=tool_calls,
            )

    return _LiveRunner()
