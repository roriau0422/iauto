"""Test doubles for the AI Mechanic context."""

from __future__ import annotations

from typing import Any

from app.ai_mechanic.agent import AgentContext, AgentRunResult


class FakeAgentRunner:
    """Records calls and returns canned `AgentRunResult`s.

    Default behaviour: echoes back the user input prefixed with
    `Mock reply:` and reports a small token count so spend rows are
    nontrivial. Tests can swap in a richer scripted reply by setting
    `next_result` before the call.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.next_result: AgentRunResult | None = None

    async def run(
        self,
        *,
        ctx: AgentContext,
        history: list[dict[str, str]],
        user_input: str,
    ) -> AgentRunResult:
        self.calls.append(
            {
                "user_input": user_input,
                "history_len": len(history),
                "vehicle_id": ctx.vehicle_id,
                "user_id": ctx.user_id,
            }
        )
        if self.next_result is not None:
            return self.next_result
        return AgentRunResult(
            final_output=f"Mock reply: {user_input}",
            prompt_tokens=42,
            completion_tokens=17,
            tool_calls=[],
        )
