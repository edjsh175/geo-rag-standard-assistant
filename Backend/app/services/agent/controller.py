"""Main Controller: sole semantic planner for Agent tool selection."""

from __future__ import annotations

import json
from typing import Sequence

from app.services.agent.model_client import ModelRequest, StageModelClient
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.tool_runtime import ToolCall, ToolObservation
from app.services.agent.tools import ToolRegistry


class MainController:
    def __init__(
        self,
        *,
        model_client: StageModelClient,
        tool_registry: ToolRegistry,
    ) -> None:
        self.model_client = model_client
        self.tool_registry = tool_registry

    async def decide(
        self,
        *,
        question: str,
        context_summary: str,
        observations: Sequence[ToolObservation],
        stage_policy: LLMStagePolicy,
    ) -> ToolCall:
        tools = "\n".join(
            f"- {spec.name}: {spec.description}"
            for spec in self.tool_registry.specs()
        )
        observation_text = "\n".join(
            f"{item.tool_name}: {dict(item.payload)}" for item in observations
        )
        request = ModelRequest(
            stage="controller",
            messages=(
                {
                    "role": "system",
                    "content": (
                        "You are the semantic planner. Choose exactly one available tool "
                        "for the next step and return JSON with tool_call_id, name, arguments. "
                        "Do not directly publish a knowledge answer.\n\nAvailable tools:\n"
                        + tools
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{question}\n\nContext:\n{context_summary}\n\n"
                        f"Observations:\n{observation_text}"
                    ),
                },
            ),
            request_reasoning=stage_policy.for_stage("controller").request_reasoning,
        )
        response = await self.model_client.complete(request)
        return self._parse_tool_call(response.content)

    def _parse_tool_call(self, content: str | None) -> ToolCall:
        if not content:
            raise ValueError("controller must return a structured tool call")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("controller must return a structured tool call") from exc
        if not isinstance(payload, dict):
            raise ValueError("controller must return a structured tool call")

        tool_call_id = payload.get("tool_call_id")
        name = payload.get("name")
        arguments = payload.get("arguments")
        if (
            not isinstance(tool_call_id, str)
            or not tool_call_id.strip()
            or not isinstance(name, str)
            or name not in self.tool_registry.names()
            or not isinstance(arguments, dict)
        ):
            raise ValueError("controller must return a structured tool call")
        return ToolCall(
            tool_call_id=tool_call_id.strip(),
            name=name,
            arguments=arguments,
        )
