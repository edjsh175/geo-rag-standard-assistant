"""Main Controller: sole semantic planner for Agent tool selection."""

from __future__ import annotations

import json
from time import monotonic
from typing import Mapping, Sequence, Any
from uuid import uuid4

from app.services.agent.model_client import ModelRequest, StageModelClient
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.structured_candidate import (
    StructuredCandidateProtocolError,
    execute_structured_candidate,
)
from app.services.agent.tool_runtime import ToolCall, ToolObservation
from app.services.agent.tools import ToolRegistry


class ControllerOutputError(ValueError):
    """Raised when the Controller fails its structured tool-call contract."""


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
        working_evidence: Sequence[Mapping[str, Any]],
        observations: Sequence[ToolObservation],
        stage_policy: LLMStagePolicy,
        model_name: str | None = None,
    ) -> ToolCall:
        tools = "\n".join(
            (
                f"- {spec.name}: {spec.description}\n"
                f"  input_schema={json.dumps(spec.input_schema, ensure_ascii=False, sort_keys=True)}"
            )
            for spec in self.tool_registry.specs()
        )
        observation_text = "\n".join(
            f"{item.tool_name}: {dict(item.payload)}" for item in observations
        )
        evidence_text = json.dumps(
            list(working_evidence),
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
        messages = (
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
                        f"Working Evidence Catalog:\n{evidence_text}\n\n"
                        f"Observations:\n{observation_text}"
                    ),
                },
        )
        execution = stage_policy.for_stage("controller")
        call_id = str(uuid4())
        deadline_at = monotonic() + execution.timeout_seconds

        async def generate_candidate(attempt):
            remaining = deadline_at - monotonic()
            if remaining <= 0:
                raise TimeoutError("controller model call deadline exceeded")
            request = ModelRequest(
                stage="controller",
                messages=messages,
                request_reasoning=(
                    execution.request_reasoning
                    if attempt.request_reasoning is None
                    else attempt.request_reasoning
                ),
                model_name=model_name,
                temperature=(0.2 if attempt.temperature is None else attempt.temperature),
                call_id=call_id,
                attempt=attempt.protocol_attempt,
                timeout_seconds=remaining,
            )
            return (await self.model_client.complete(request)).content

        try:
            return await execute_structured_candidate(
                generate=generate_candidate,
                validate=self._parse_tool_call,
            )
        except StructuredCandidateProtocolError as exc:
            raise ControllerOutputError(
                "controller must return a structured tool call"
            ) from exc

    def _parse_tool_call(self, content: str | None) -> ToolCall:
        if not content:
            raise ControllerOutputError("controller must return a structured tool call")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ControllerOutputError("controller must return a structured tool call") from exc
        if not isinstance(payload, dict):
            raise ControllerOutputError("controller must return a structured tool call")

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
            raise ControllerOutputError("controller must return a structured tool call")
        return ToolCall(
            tool_call_id=tool_call_id.strip(),
            name=name,
            arguments=arguments,
        )
