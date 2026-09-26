"""Main Controller: sole semantic planner for Agent tool and control action selection."""

from __future__ import annotations

import json
from time import monotonic
from typing import Any, Mapping, Sequence
from uuid import uuid4

from app.services.agent.controller_protocol import (
    CLARIFY_ACTION,
    COMPOSE_ANSWER_ACTION,
    DIRECT_ANSWER_ACTION,
    TOOL_CALL_ACTION,
    ControllerDecision,
    ExecutableActionState,
    build_control_action_contracts,
    build_controller_decision_schema,
    validate_controller_decision_payload,
)
from app.services.agent.model_client import ModelRequest, StageModelClient
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.structured_candidate import (
    StructuredCandidateProtocolError,
    execute_structured_candidate,
)
from app.services.agent.tool_runtime import ToolObservation
from app.services.agent.tools import ToolRegistry


class ControllerOutputError(ValueError):
    """Raised when the Controller fails its structured decision contract."""


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
        projection: Any | None = None,
        action_state: ExecutableActionState | None = None,
        observations: Sequence[ToolObservation] = (),
        stage_policy: LLMStagePolicy,
        model_name: str | None = None,
        question: str | None = None,
        context_summary: str | None = None,
        working_evidence: Sequence[Mapping[str, Any]] | None = None,
        available_tool_names: set[str] | frozenset[str] | None = None,
        available_control_actions: set[str] | frozenset[str] | None = None,
    ) -> ControllerDecision:
        # Unpack from projection if provided
        if projection is not None:
            effective_question = projection.user_question
            effective_context_summary = projection.conversation_text
            effective_working_evidence = projection.working_evidence
            effective_evidence_catalog = (
                projection.evidence_catalog if hasattr(projection, "evidence_catalog") and projection.evidence_catalog
                else effective_working_evidence
            )
            effective_runtime_facts = (
                dict(projection.runtime_facts) if hasattr(projection, "runtime_facts") and projection.runtime_facts
                else {}
            )
            effective_map_context = getattr(projection, "map_context", None)
        else:
            effective_question = question or ""
            effective_context_summary = context_summary or ""
            effective_working_evidence = working_evidence or ()
            effective_evidence_catalog = effective_working_evidence
            effective_runtime_facts = {}
            effective_map_context = None

        if action_state is None:
            capabilities = (
                frozenset(available_tool_names)
                if available_tool_names is not None
                else frozenset(self.tool_registry.names())
            )
            control_actions = (
                frozenset(available_control_actions)
                if available_control_actions is not None
                else frozenset({COMPOSE_ANSWER_ACTION, DIRECT_ANSWER_ACTION})
            )
            selectable_ids = frozenset(
                ev.get("evidence_id")
                for ev in effective_evidence_catalog
                if isinstance(ev, Mapping) and ev.get("evidence_id")
            )
            action_state = ExecutableActionState(
                available_capabilities=capabilities,
                available_control_actions=control_actions,
                selectable_evidence_ids=selectable_ids,
                has_evidence=bool(selectable_ids),
            )

        active_specs = self.tool_registry.specs_for(action_state.available_capabilities)
        tools_text_parts = []
        for spec in active_specs:
            spec_desc = [f"- {spec.name}: {spec.description}"]
            if getattr(spec, "use_when", None):
                spec_desc.append(f"  When to use: {spec.use_when}")
            if getattr(spec, "avoid_when", None):
                spec_desc.append(f"  Avoid when: {spec.avoid_when}")
            spec_desc.append(f"  input_schema={json.dumps(spec.input_schema, ensure_ascii=False, sort_keys=True)}")
            tools_text_parts.append("\n".join(spec_desc))
        tools_text = "\n".join(tools_text_parts) if tools_text_parts else "No external tools available."

        control_contracts = build_control_action_contracts(action_state.allowed_answer_kinds)
        control_actions_text_parts = []
        for act in sorted(action_state.available_control_actions):
            if act in control_contracts:
                c = control_contracts[act]
                control_actions_text_parts.append(
                    f"- {c.name}: {c.purpose}\n"
                    f"  When to use: {c.use_when}\n"
                    f"  Avoid when: {c.avoid_when}\n"
                    f"  Schema: {json.dumps(c.input_schema, ensure_ascii=False)}"
                )
        control_text = "\n".join(control_actions_text_parts) if control_actions_text_parts else "None."

        capability_schemas = {spec.name: spec.input_schema for spec in active_specs}
        decision_schema = build_controller_decision_schema(
            capability_schemas=capability_schemas,
            allowed_control_actions=list(action_state.available_control_actions),
            allowed_answer_kinds=list(action_state.allowed_answer_kinds),
        )

        observation_text = "\n".join(
            f"{item.tool_name}: {dict(item.payload)}" for item in observations
        ) if observations else "None."

        evidence_text = json.dumps(
            list(effective_evidence_catalog),
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )

        runtime_facts_text = (
            json.dumps(effective_runtime_facts, ensure_ascii=False, default=str, sort_keys=True)
            if effective_runtime_facts
            else "None."
        )

        system_prompt = (
            "You are the Main Controller and semantic planner for the GeoAI Agent.\n"
            "Choose exactly one action for the next step. You must return only valid JSON matching the schema.\n\n"
            "Action Space:\n"
            f"1. Control Actions:\n{control_text}\n\n"
            f"2. Executable Capabilities (Tools):\n{tools_text}\n\n"
            "Rules:\n"
            "- To call a capability: {\"action\":\"tool_call\",\"tool\":\"...\",\"arguments\":{...}}\n"
            "  (Legacy {\"name\":\"...\",\"arguments\":{...}} is also accepted).\n"
            "- To finalize a knowledge answer: {\"action\":\"compose_answer\",\"arguments\":{\"answer_kind\":\"knowledge_answer\",\"selected_evidence_ids\":[...]}}\n"
            "- You may directly select evidence from the Evidence Catalog (including historical session evidence) for compose_answer without re-retrieving if it is sufficient.\n"
            "- If evidence is insufficient, call retrieve_kb to search the knowledge base or search_evidence_memory to search historical evidence.\n"
            "- To answer non-knowledge conversational or meta requests: {\"action\":\"direct_answer\",\"answer\":\"...\"}\n"
            "- To request user clarification: {\"action\":\"clarify\",\"arguments\":{}}\n"
            "- Do not generate tool_call_id; the application assigns it.\n"
            "- For knowledge questions, never use direct_answer; you must select evidence via compose_answer."
        )

        user_content_parts = [
            f"Question:\n{effective_question}\n",
            f"Context:\n{effective_context_summary}\n",
            f"Evidence Catalog (Working & Historical):\n{evidence_text}\n",
            f"Runtime Facts:\n{runtime_facts_text}\n",
            f"Observations:\n{observation_text}",
        ]
        if effective_map_context:
            user_content_parts.append(
                f"\nMap Context:\n{json.dumps(dict(effective_map_context), ensure_ascii=False, default=str)}"
            )

        user_content = "\n".join(user_content_parts)

        messages = (
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
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
                response_schema=decision_schema,
            )
            return (await self.model_client.complete(request)).content

        try:
            return await execute_structured_candidate(
                generate=generate_candidate,
                validate=lambda content: self._parse_decision(
                    content,
                    state=action_state,
                    tool_call_id=call_id,
                ),
            )
        except StructuredCandidateProtocolError as exc:
            raise ControllerOutputError(
                f"controller must return a structured tool call: {exc}"
            ) from exc

    def _parse_decision(
        self,
        content: str | None,
        *,
        state: ExecutableActionState,
        tool_call_id: str,
    ) -> ControllerDecision:
        if not content:
            raise ControllerOutputError("controller output is empty")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ControllerOutputError("controller output is not valid json") from exc
        if not isinstance(payload, dict):
            raise ControllerOutputError("controller output must be a json object")
        try:
            return validate_controller_decision_payload(
                payload,
                state=state,
                registry=self.tool_registry,
                tool_call_id=tool_call_id,
            )
        except ValueError as exc:
            raise ControllerOutputError(str(exc)) from exc
