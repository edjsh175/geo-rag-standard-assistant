"""Provider-independent Controller decision protocol and schema builder for GeoAI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
import re
from types import MappingProxyType
from typing import Any

from app.services.agent.tools import ToolRegistry, ToolSpec

COMPOSE_ANSWER_ACTION = "compose_answer"
DIRECT_ANSWER_ACTION = "direct_answer"
CLARIFY_ACTION = "clarify"
TOOL_CALL_ACTION = "tool_call"


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True)
class ControlActionContract:
    name: str
    purpose: str
    use_when: str
    avoid_when: str
    result_semantics: str
    input_schema: dict[str, Any]


def build_control_action_contracts(
    allowed_answer_kinds: Sequence[str] = ("knowledge_answer", "limitation_or_clarification"),
) -> dict[str, ControlActionContract]:
    return {
        CLARIFY_ACTION: ControlActionContract(
            name=CLARIFY_ACTION,
            purpose="请求用户在 Runtime 已确认的实体或空间作用域候选中完成身份确认，并暂停当前轮次。",
            use_when="当前存在合法且存在歧义的实体或图层/区域候选，且继续决策前必须由用户确认。",
            avoid_when="没有权威候选时不得使用；严禁模型自主捏造选项、候选或 ID。",
            result_semantics="Runtime 冻结候选并向用户呈现澄清请求；用户选择后继续决策。",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        COMPOSE_ANSWER_ACTION: ControlActionContract(
            name=COMPOSE_ANSWER_ACTION,
            purpose="提交 Answer Contract，结束当前 Planning 阶段并进入正式 Answer Generator / Reviewer 闭环。",
            use_when="当前收集的证据已足以回答用户知识型问题或说明明确限制。",
            avoid_when="证据仍不足以支撑结论，或试图绕过 Reviewer 审核时。",
            result_semantics="冻结选定的证据并生成候选答案；通过审核后发布给用户。",
            input_schema={
                "type": "object",
                "properties": {
                    "answer_mode": {"type": "string", "enum": ["full", "partial"], "description": "回答完整度。"},
                    "answer_kind": {"type": "string", "enum": list(allowed_answer_kinds), "description": "回答事实边界。"},
                    "selected_evidence_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                        "description": "knowledge_answer 必填；Controller 显式挑选支持本次回答的证据 ID。",
                    },
                    "answer_requirements": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "description": "传递给 Answer Generator 的重点要求与结构化指令。",
                    },
                },
                "required": ["answer_kind"],
                "allOf": [
                    {
                        "if": {
                            "properties": {"answer_kind": {"const": "knowledge_answer"}},
                            "required": ["answer_kind"],
                        },
                        "then": {"required": ["selected_evidence_ids"]},
                    }
                ],
                "additionalProperties": False,
            },
        ),
        DIRECT_ANSWER_ACTION: ControlActionContract(
            name=DIRECT_ANSWER_ACTION,
            purpose="直接发布不依赖内部知识库证据的完整回答正文；适用于闲聊、元状态解释、执行过程汇报等。",
            use_when="不需要内部检索证据的日常问答、会话控制或已执行动作说明。",
            avoid_when="严禁用于需要标准规范条文、地理实体事实或检索数据支撑的业务回答。",
            result_semantics="Controller 提供完整 answer 文本并直接发布，不经过 Answer Generator 与 Reviewer。",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
    }


@dataclass(frozen=True)
class ExecutableActionState:
    """Canonical single-source-of-truth action surface for Controller."""

    available_capabilities: frozenset[str]
    available_control_actions: frozenset[str]
    allowed_answer_kinds: tuple[str, ...] = ("knowledge_answer", "limitation_or_clarification")
    identity_status: str = "resolved"

    @classmethod
    def compute(
        cls,
        *,
        registry: ToolRegistry,
        map_context: Mapping[str, Any] | None = None,
        identity_status: str = "resolved",
        has_evidence: bool = True,
        forbid_finalize: bool = False,
    ) -> "ExecutableActionState":
        from app.services.agent.tools import executable_tool_names

        capabilities = executable_tool_names(registry, map_context)
        control_actions: set[str] = set()

        if not forbid_finalize:
            control_actions.add(DIRECT_ANSWER_ACTION)
            control_actions.add(COMPOSE_ANSWER_ACTION)

        if identity_status in {"ambiguous", "unresolved"} and not forbid_finalize:
            control_actions.add(CLARIFY_ACTION)

        allowed_kinds = ("knowledge_answer", "limitation_or_clarification")
        return cls(
            available_capabilities=frozenset(capabilities),
            available_control_actions=frozenset(control_actions),
            allowed_answer_kinds=allowed_kinds,
            identity_status=identity_status,
        )


@dataclass(frozen=True)
class ControllerDecision:
    """Validated structured decision from Controller."""

    action: str  # "tool_call", "compose_answer", "direct_answer", "clarify"
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    answer: str | None = None
    reason: str | None = None
    tool_call_id: str | None = None

    @property
    def name(self) -> str:
        """Compatibility property for legacy callers expecting decision.name."""
        if self.action == TOOL_CALL_ACTION and self.tool:
            return self.tool
        return self.action


def _protocol_identifier(value: str) -> str:
    normalized = str(value or "").strip().strip("`").casefold()
    return re.sub(r"[-\s]+", "_", normalized)


def normalize_legacy_controller_wire(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize legacy wire variants into canonical protocol shape."""
    normalized = dict(payload)
    action = str(normalized.get("action") or "").strip().casefold()

    # Legacy: {"name": "retrieve_kb", "arguments": {...}}
    name = normalized.get("name")
    if not action and name:
        name_str = str(name).strip()
        if name_str in {COMPOSE_ANSWER_ACTION, DIRECT_ANSWER_ACTION, CLARIFY_ACTION}:
            action = name_str
            normalized["action"] = action
            normalized.pop("name", None)
        else:
            action = TOOL_CALL_ACTION
            normalized["action"] = TOOL_CALL_ACTION
            normalized["tool"] = name_str
            normalized.pop("name", None)

    tool = str(normalized.get("tool") or normalized.get("tool_name") or "").strip()
    if action == TOOL_CALL_ACTION and tool:
        normalized["tool"] = tool
        normalized.pop("tool_name", None)
        if tool == COMPOSE_ANSWER_ACTION:
            normalized["action"] = COMPOSE_ANSWER_ACTION
            normalized.pop("tool", None)
            action = COMPOSE_ANSWER_ACTION
        elif tool == CLARIFY_ACTION:
            normalized["action"] = CLARIFY_ACTION
            normalized.pop("tool", None)
            action = CLARIFY_ACTION
        elif tool == DIRECT_ANSWER_ACTION:
            normalized["action"] = DIRECT_ANSWER_ACTION
            normalized.pop("tool", None)
            action = DIRECT_ANSWER_ACTION

    # Legacy compose_answer arguments: evidence_ids -> selected_evidence_ids
    if action == COMPOSE_ANSWER_ACTION:
        raw_args = normalized.get("arguments")
        args_dict = dict(raw_args) if isinstance(raw_args, Mapping) else {}
        if "evidence_ids" in args_dict and "selected_evidence_ids" not in args_dict:
            args_dict["selected_evidence_ids"] = args_dict.pop("evidence_ids")
        if "selected_evidence_ids" not in args_dict and "selected_evidence_ids" in normalized:
            args_dict["selected_evidence_ids"] = normalized.pop("selected_evidence_ids")
        if "answer_kind" not in args_dict:
            args_dict["answer_kind"] = "knowledge_answer"
        normalized["arguments"] = args_dict

    # Normalize reason
    if "reason" not in normalized and "thought" in normalized:
        normalized["reason"] = normalized.pop("thought")

    return normalized


def validate_controller_decision_payload(
    payload: Mapping[str, Any],
    *,
    state: ExecutableActionState,
    registry: ToolRegistry,
    tool_call_id: str,
) -> ControllerDecision:
    """Validate wire payload against current ExecutableActionState."""
    normalized = normalize_legacy_controller_wire(payload)
    action = str(normalized.get("action") or "").strip()
    reason = str(normalized.get("reason") or "").strip() or None

    if action == TOOL_CALL_ACTION:
        tool = str(normalized.get("tool") or "").strip()
        if not tool or tool not in state.available_capabilities:
            raise ValueError(
                f"malformed_tool_call: tool '{tool}' is not available in current state"
            )
        raw_arguments = normalized.get("arguments")
        if not isinstance(raw_arguments, Mapping):
            raise ValueError("malformed_tool_call: arguments must be an object")
        validated_args = registry.validate_arguments(tool, raw_arguments)
        return ControllerDecision(
            action=TOOL_CALL_ACTION,
            tool=tool,
            arguments=dict(validated_args),
            reason=reason,
            tool_call_id=tool_call_id,
        )

    if action == COMPOSE_ANSWER_ACTION:
        if COMPOSE_ANSWER_ACTION not in state.available_control_actions:
            raise ValueError("malformed_decision_action: compose_answer is not currently available")
        raw_arguments = normalized.get("arguments")
        if not isinstance(raw_arguments, Mapping):
            raise ValueError("malformed_compose_answer: arguments must be an object")
        args_dict = dict(raw_arguments)
        answer_kind = str(args_dict.get("answer_kind") or "").strip()
        if not answer_kind or answer_kind not in state.allowed_answer_kinds:
            raise ValueError(f"malformed_compose_answer: invalid answer_kind '{answer_kind}'")

        selected_ids = args_dict.get("selected_evidence_ids")
        if answer_kind == "knowledge_answer":
            if not isinstance(selected_ids, list) or not selected_ids:
                raise ValueError(
                    "malformed_compose_answer: selected_evidence_ids must be a non-empty array for knowledge_answer"
                )
            for eid in selected_ids:
                if not isinstance(eid, str) or not eid.strip():
                    raise ValueError("malformed_compose_answer: selected_evidence_ids items must be non-empty strings")
        # Ensure backward compatibility in arguments
        args_dict.setdefault("evidence_ids", list(selected_ids or []))
        return ControllerDecision(
            action=COMPOSE_ANSWER_ACTION,
            arguments=args_dict,
            reason=reason,
            tool_call_id=tool_call_id,
        )

    if action == DIRECT_ANSWER_ACTION:
        if DIRECT_ANSWER_ACTION not in state.available_control_actions:
            raise ValueError("malformed_decision_action: direct_answer is not currently available")
        raw_answer = normalized.get("answer")
        if not isinstance(raw_answer, str) or not raw_answer.strip():
            raise ValueError("malformed_direct_answer: answer must be a non-empty string")
        answer_text = raw_answer.strip()

        # Reject protocol identifier tokens disguised as answers
        reserved = {
            _protocol_identifier(s)
            for s in (
                TOOL_CALL_ACTION,
                COMPOSE_ANSWER_ACTION,
                DIRECT_ANSWER_ACTION,
                CLARIFY_ACTION,
                *state.available_capabilities,
            )
        }
        if _protocol_identifier(answer_text) in reserved:
            raise ValueError(
                "malformed_direct_answer: answer must be user-facing text, not a bare protocol identifier"
            )
        return ControllerDecision(
            action=DIRECT_ANSWER_ACTION,
            answer=answer_text,
            arguments={},
            reason=reason,
            tool_call_id=tool_call_id,
        )

    if action == CLARIFY_ACTION:
        if CLARIFY_ACTION not in state.available_control_actions:
            raise ValueError("malformed_decision_action: clarify is not currently available")
        return ControllerDecision(
            action=CLARIFY_ACTION,
            arguments={},
            reason=reason,
            tool_call_id=tool_call_id,
        )

    raise ValueError(f"malformed_decision_action: unknown action '{action}'")


def build_controller_decision_schema(
    *,
    capability_schemas: Mapping[str, Mapping[str, Any]],
    allowed_answer_kinds: Sequence[str] = ("knowledge_answer", "limitation_or_clarification"),
    allowed_control_actions: Sequence[str] = (
        CLARIFY_ACTION,
        COMPOSE_ANSWER_ACTION,
        DIRECT_ANSWER_ACTION,
    ),
) -> dict[str, Any]:
    """Build the request-scoped JSON Schema for Controller decisions."""
    contracts = build_control_action_contracts(allowed_answer_kinds)
    branches: list[dict[str, Any]] = []
    controls = set(allowed_control_actions)

    if COMPOSE_ANSWER_ACTION in controls:
        branches.append({
            "type": "object",
            "properties": {
                "action": {"const": COMPOSE_ANSWER_ACTION},
                "arguments": dict(contracts[COMPOSE_ANSWER_ACTION].input_schema),
                "reason": {"type": "string"},
            },
            "required": ["action", "arguments"],
            "additionalProperties": False,
        })

    if CLARIFY_ACTION in controls:
        branches.append({
            "type": "object",
            "properties": {
                "action": {"const": CLARIFY_ACTION},
                "arguments": {"type": "object", "properties": {}, "additionalProperties": False},
                "reason": {"type": "string"},
            },
            "required": ["action", "arguments"],
            "additionalProperties": False,
        })

    if capability_schemas:
        tool_branches = []
        for name, spec in capability_schemas.items():
            s = dict(spec)
            s.setdefault("type", "object")
            tool_branches.append({
                "type": "object",
                "properties": {
                    "action": {"const": TOOL_CALL_ACTION},
                    "tool": {"const": name},
                    "arguments": s,
                    "reason": {"type": "string"},
                },
                "required": ["action", "tool", "arguments"],
                "additionalProperties": False,
            })
        branches.append({
            "type": "object",
            "properties": {
                "action": {"const": TOOL_CALL_ACTION},
                "tool": {"type": "string", "enum": list(capability_schemas)},
                "arguments": {"type": "object"},
                "reason": {"type": "string"},
            },
            "required": ["action", "tool", "arguments"],
            "oneOf": tool_branches,
        })

    if DIRECT_ANSWER_ACTION in controls:
        branches.append({
            "type": "object",
            "properties": {
                "action": {"const": DIRECT_ANSWER_ACTION},
                "answer": {
                    "type": "string",
                    "minLength": 1,
                    "description": "完整用户可见回答，不得包含工具名或占位符。",
                },
                "reason": {"type": "string"},
                "arguments": {"type": "object", "maxProperties": 0},
            },
            "required": ["action", "answer"],
            "additionalProperties": False,
        })

    return {"oneOf": branches}
