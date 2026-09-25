"""Grounded answer generation from immutable Frozen Evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from time import monotonic
from uuid import uuid4

from app.services.agent.contracts import FrozenEvidenceSnapshot, MapAction
from app.services.agent.model_client import ModelRequest, StageModelClient
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.structured_candidate import (
    StructuredCandidateProtocolError,
    execute_structured_candidate,
)


class AnswerGenerationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AnswerUnit:
    unit_id: str
    text: str
    citations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    kind: str
    answer: str
    citations: tuple[str, ...] = ()
    map_action: MapAction | None = None
    units: tuple[AnswerUnit, ...] = ()


class AnswerGenerator:
    def __init__(self, *, model_client: StageModelClient) -> None:
        self.model_client = model_client

    async def generate(
        self,
        *,
        question: str,
        snapshot: FrozenEvidenceSnapshot | None,
        stage_policy: LLMStagePolicy,
        model_name: str | None = None,
    ) -> GeneratedAnswer:
        if snapshot is None or not snapshot.items:
            raise AnswerGenerationError(
                "knowledge answers require a non-empty Frozen Evidence snapshot"
            )

        request = self._build_request(
            question=question,
            snapshot=snapshot,
            stage_policy=stage_policy,
        )
        execution = stage_policy.for_stage("answer_generation")
        call_id = str(uuid4())
        deadline_at = monotonic() + execution.timeout_seconds
        async def generate_candidate(attempt):
            remaining = deadline_at - monotonic()
            if remaining <= 0:
                raise TimeoutError("answer generation model call deadline exceeded")
            call = ModelRequest(
                stage="answer_generation",
                messages=request.messages,
                request_reasoning=(
                    request.request_reasoning
                    if attempt.request_reasoning is None
                    else attempt.request_reasoning
                ),
                model_name=model_name,
                temperature=(0.2 if attempt.temperature is None else attempt.temperature),
                call_id=call_id,
                attempt=attempt.protocol_attempt,
                timeout_seconds=remaining,
            )
            return (await self.model_client.complete(call)).content

        try:
            return await execute_structured_candidate(
                generate=generate_candidate,
                validate=lambda content: self._parse(content, snapshot=snapshot),
            )
        except StructuredCandidateProtocolError as exc:
            raise AnswerGenerationError(
                "answer generation failed to produce valid structured output"
            ) from exc

    async def generate_repair(
        self,
        *,
        question: str,
        snapshot: FrozenEvidenceSnapshot,
        base_answer: GeneratedAnswer,
        repair_scope: Mapping[str, Any],
        stage_policy: LLMStagePolicy,
        model_name: str | None = None,
    ) -> GeneratedAnswer:
        evidence_text = "\n\n".join(
            f"[{item.citation_id}] {item.title}\n{item.text}"
            for item in snapshot.items
        )
        repair_instructions = (
            "You are performing a constrained repair of a previous answer draft.\n"
            f"Repair Contract Version: {repair_scope.get('contract_version')}\n"
            f"Immutable Units (MUST be preserved exactly, no changes): {repair_scope.get('immutable_units')}\n"
            f"Editable Units (Must be revised to adhere strictly to Frozen Evidence, or omitted): {json.dumps(repair_scope.get('editable_units'), ensure_ascii=False)}\n"
            "Rules:\n"
            "1. Preserved units must keep their exact unit_id, text, and citations.\n"
            "2. Editable units must only reference allowed evidence from the Frozen Evidence.\n"
            "3. Do not invent new facts or add new units.\n"
            "4. Return valid JSON containing units array and answer string."
        )
        base_units_json = json.dumps(
            [{"unit_id": u.unit_id, "text": u.text, "citations": list(u.citations)} for u in base_answer.units],
            ensure_ascii=False,
        )
        messages = (
            {
                "role": "system",
                "content": f"{repair_instructions}\n\nFrozen Evidence:\n{evidence_text}",
            },
            {
                "role": "user",
                "content": f"Question: {question}\n\nOriginal Draft Units:\n{base_units_json}\n\nRepair the draft according to the contract.",
            },
        )
        execution = stage_policy.for_stage("answer_generation")
        call_id = str(uuid4())
        deadline_at = monotonic() + execution.timeout_seconds

        async def generate_candidate(attempt):
            remaining = deadline_at - monotonic()
            if remaining <= 0:
                raise TimeoutError("answer generation repair model call deadline exceeded")
            call = ModelRequest(
                stage="answer_generation",
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
            return (await self.model_client.complete(call)).content

        try:
            return await execute_structured_candidate(
                generate=generate_candidate,
                validate=lambda content: self._parse(content, snapshot=snapshot),
            )
        except StructuredCandidateProtocolError as exc:
            raise AnswerGenerationError(
                "answer generation repair failed to produce valid structured output"
            ) from exc

    def _build_request(
        self,
        *,
        question: str,
        snapshot: FrozenEvidenceSnapshot,
        stage_policy: LLMStagePolicy,
    ) -> ModelRequest:
        evidence_text = "\n\n".join(
            f"[{item.citation_id}] {item.title}\n{item.text}"
            for item in snapshot.items
        )
        output_schema = self._output_schema(snapshot)
        messages = (
            {
                "role": "system",
                "content": (
                    "Generate only a grounded answer from the provided Frozen Evidence. "
                    "Return only JSON that satisfies the following schema exactly. "
                    "Do not invent alternative kind labels such as summary or grounded_summary. "
                    "Do not introduce external facts.\n\n"
                    f"Output JSON Schema:\n{json.dumps(output_schema, ensure_ascii=False, sort_keys=True)}"
                ),
            },
            {
                "role": "user",
                "content": f"Question:\n{question}\n\nFrozen Evidence:\n{evidence_text}",
            },
        )
        return ModelRequest(
            stage="answer_generation",
            messages=messages,
            request_reasoning=stage_policy.for_stage(
                "answer_generation"
            ).request_reasoning,
            model_name=None,
        )

    @staticmethod
    def _output_schema(snapshot: FrozenEvidenceSnapshot) -> dict:
        allowed_citations = [item.citation_id for item in snapshot.items]
        return {
            "type": "object",
            "properties": {
                "kind": {"const": "knowledge_answer"},
                "units": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "unit_id": {"type": "string", "minLength": 1},
                            "text": {"type": "string", "minLength": 1},
                            "citations": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string", "enum": allowed_citations},
                            },
                        },
                        "required": ["unit_id", "text", "citations"],
                        "additionalProperties": False,
                    },
                },
                "map_action": {
                    "anyOf": [
                        {"type": "null"},
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string"},
                                "target": {"type": "string"},
                                "adcode": {"type": ["string", "null"]},
                                "name": {"type": ["string", "null"]},
                                "payload": {"type": ["object", "null"]},
                            },
                            "required": ["type", "target"],
                            "additionalProperties": False,
                        },
                    ]
                },
            },
            "required": ["kind", "units"],
            "additionalProperties": False,
        }

    @staticmethod
    def _parse(
        content: str | None,
        *,
        snapshot: FrozenEvidenceSnapshot,
    ) -> GeneratedAnswer:
        if not content or not content.strip():
            raise ValueError("empty structured output")
        try:
            payload = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            raise ValueError("invalid structured output")
        if not isinstance(payload, dict):
            raise ValueError("invalid structured output")

        kind = payload.get("kind")
        if kind != "knowledge_answer":
            raise ValueError(
                f"invalid answer kind: expected 'knowledge_answer', got {kind!r}"
            )

        allowed = {item.citation_id for item in snapshot.items}
        raw_units = payload.get("units")
        units: list[AnswerUnit] = []
        if not isinstance(raw_units, list) or not raw_units:
            raise ValueError("answer units are required")
        seen_ids: set[str] = set()
        for raw_unit in raw_units:
            if not isinstance(raw_unit, dict):
                raise ValueError("invalid answer unit")
            unit_id = raw_unit.get("unit_id")
            text = raw_unit.get("text")
            citations = raw_unit.get("citations")
            if (
                not isinstance(unit_id, str)
                or not unit_id.strip()
                or unit_id in seen_ids
                or not isinstance(text, str)
                or not text.strip()
                or not isinstance(citations, list)
                or not citations
                or not all(isinstance(value, str) and value in allowed for value in citations)
            ):
                raise ValueError("invalid answer unit")
            seen_ids.add(unit_id)
            units.append(
                AnswerUnit(
                    unit_id=unit_id.strip(),
                    text=text.strip(),
                    citations=tuple(citations),
                )
            )
        answer = "\n".join(unit.text for unit in units)
        citations = tuple(
            dict.fromkeys(citation for unit in units for citation in unit.citations)
        )
        map_action = None
        raw_map_action = payload.get("map_action")
        if raw_map_action is not None:
            if not isinstance(raw_map_action, dict):
                raise ValueError("invalid map action")
            action_type = raw_map_action.get("type")
            target = raw_map_action.get("target")
            if not isinstance(action_type, str) or not isinstance(target, str):
                raise ValueError("invalid map action")
            raw_payload = raw_map_action.get("payload")
            if raw_payload is not None and not isinstance(raw_payload, dict):
                raise ValueError("invalid map action")
            map_action = MapAction(
                type=action_type,
                target=target,
                adcode=(str(raw_map_action["adcode"]) if raw_map_action.get("adcode") is not None else None),
                name=(str(raw_map_action["name"]) if raw_map_action.get("name") is not None else None),
                payload=raw_payload,
            )
        return GeneratedAnswer(
            kind="knowledge_answer",
            answer=answer,
            citations=citations,
            map_action=map_action,
            units=tuple(units),
        )
