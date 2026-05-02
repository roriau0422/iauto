"""AI Mechanic — multi-modal diagnostic agent (Phase 3).

OpenAI Agents SDK + LiteLLM extension routes Gemini
(`gemini-3-flash-preview`) as the agent model. Tools are bound to a
`RunContextWrapper[AgentContext]` that carries the active DB session
and the calling user's vehicle id, so the agent's tool calls operate
inside the same transaction as the message persistence.

Per arch §13:
  - Cost controls (model routing, per-user daily Redis rate limit,
    embedding cache, spend log) ship in this session — bolt-on cost
    control is what bites.
  - LLM never owns source-of-truth: the four tools
    (`get_vehicle_context`, `search_knowledge_base`, `search_parts`,
    `estimate_labor_cost`) hit the deterministic spine.
  - Voice (Whisper), warning lights (MobileNet), open-vocab visual,
    engine-sound (audio LLM) all land in later sessions.
"""
