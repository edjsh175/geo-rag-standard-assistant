"""Provider-independent Controller decision protocol and schema builder for GeoAI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
import re
import warnings
from types import MappingProxyType
from typing import Any

from app.services.agent.identity import IdentityResolution
from app.services.agent.tools import ToolRegistry, ToolSpec

COMPOSE_ANSWER_ACTION = "compose_answer"
DIRECT_ANSWER_ACTION = "direct_answer"

LEGACY_CONTROLLER_WIRE_REMOVAL_AFTER = "2026-12-31"
LEGACY_CONTROLLER_WIRE_PROTOCOL_VERSION = "v1"
CLARIFY_ACTION = "clarify"
LIMITATION_ACTION = "limitation"
TOOL_CALL_ACTION = "tool_call"


class ControllerOutputError(ValueError):
    """Raised when the Controller fails its structured decision contract."""


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
            purpose="请求用户确认 Runtime 已解析出的歧义实体候选，并暂停当前轮次。",
            use_when="仅当当前 Runtime IdentityResolution 存在至少两个合法实体候选时使用。",
            avoid_when="禁止用于一般意图、空间范围或参数澄清；禁止由模型自行生成候选或问题。",
            result_semantics="Runtime 根据实体候选确定性生成确认内容；Controller 不提供文本或选项。",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        LIMITATION_ACTION: ControlActionContract(
            name=LIMITATION_ACTION,
            purpose="当知识库无证据、超出系统知识范围或存在明确系统限制无法得出结论时，发布限制说明。",
            use_when="知识库检索无匹配证据、用户要求说明无证据时的系统限制、或无法安全给出专业结论时使用。",
            avoid_when="存在充分知识库证据可以回答问题时禁止使用。",
            result_semantics="向用户发布 limitation 状态的安全限制说明并完成当前轮次。",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "minLength": 1, "description": "系统限制说明正文。"}
                },
                "required": ["message"],
                "additionalProperties": False,
            },
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
    selectable_evidence_ids: frozenset[str] = frozenset()
    has_evidence: bool = True
    provider_health: Mapping[str, bool] = field(default_factory=_empty_mapping)
    identity_resolution: IdentityResolution | None = None

    @classmethod
    def compute(
        cls,
        *,
        registry: ToolRegistry,
        map_context: Mapping[str, Any] | None = None,
        identity_resolution: IdentityResolution | None = None,
        has_evidence: bool = True,
        selectable_evidence_ids: Sequence[str] | frozenset[str] | None = None,
        forbid_finalize: bool = False,
        provider_health: Mapping[str, bool] | None = None,
    ) -> "ExecutableActionState":
        from app.services.agent.tools import executable_tool_names

        capabilities = executable_tool_names(registry, map_context, provider_health)
        control_actions: set[str] = set()

        if selectable_evidence_ids is not None:
            selectable_ids = frozenset(selectable_evidence_ids)
            effective_has_evidence = len(selectable_ids) > 0
        else:
            selectable_ids = frozenset()
            effective_has_evidence = bool(has_evidence)

        if not forbid_finalize:
            control_actions.add(DIRECT_ANSWER_ACTION)
            control_actions.add(LIMITATION_ACTION)
            if identity_resolution is not None and identity_resolution.requires_confirmation:
                control_actions.add(CLARIFY_ACTION)
            if effective_has_evidence:
                control_actions.add(COMPOSE_ANSWER_ACTION)

        if effective_has_evidence:
            allowed_kinds = ("knowledge_answer", "limitation_or_clarification")
        else:
            # P0-7: 0 selectable evidence: knowledge compose not exposed
            allowed_kinds = ("limitation_or_clarification",)

        return cls(
            available_capabilities=frozenset(capabilities),
            available_control_actions=frozenset(control_actions),
            allowed_answer_kinds=allowed_kinds,
            identity_status=identity_resolution.status if identity_resolution is not None else "resolved",
            selectable_evidence_ids=selectable_ids,
            has_evidence=effective_has_evidence,
            provider_health=provider_health or {},
            identity_resolution=identity_resolution,
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
    legacy_used = False

    # Legacy: {"name": "retrieve_kb", "arguments": {...}}
    name = normalized.get("name")
    if not action and name:
        legacy_used = True
        name_str = str(name).strip()
        if name_str in {COMPOSE_ANSWER_ACTION, DIRECT_ANSWER_ACTION, CLARIFY_ACTION, LIMITATION_ACTION}:
            action = name_str
            normalized["action"] = action
            normalized.pop("name", None)
        else:
            action = TOOL_CALL_ACTION
            normalized["action"] = TOOL_CALL_ACTION
            normalized["tool"] = name_str
            normalized.pop("name", None)

    tool = str(normalized.get("tool") or normalized.get("tool_name") or "").strip()
    if "tool_name" in normalized:
        legacy_used = True
    if action == TOOL_CALL_ACTION and tool:
        normalized["tool"] = tool
        normalized.pop("tool_name", None)
        if tool == COMPOSE_ANSWER_ACTION:
            legacy_used = True
            normalized["action"] = COMPOSE_ANSWER_ACTION
            normalized.pop("tool", None)
            action = COMPOSE_ANSWER_ACTION
        elif tool == CLARIFY_ACTION:
            legacy_used = True
            normalized["action"] = CLARIFY_ACTION
            normalized.pop("tool", None)
            action = CLARIFY_ACTION
        elif tool == LIMITATION_ACTION:
            legacy_used = True
            normalized["action"] = LIMITATION_ACTION
            normalized.pop("tool", None)
            action = LIMITATION_ACTION
        elif tool == DIRECT_ANSWER_ACTION:
            legacy_used = True
            normalized["action"] = DIRECT_ANSWER_ACTION
            normalized.pop("tool", None)
            action = DIRECT_ANSWER_ACTION

    # Legacy compose_answer arguments: evidence_ids -> selected_evidence_ids
    if action == COMPOSE_ANSWER_ACTION:
        raw_args = normalized.get("arguments")
        args_dict = dict(raw_args) if isinstance(raw_args, Mapping) else {}
        if "evidence_ids" in args_dict and "selected_evidence_ids" not in args_dict:
            legacy_used = True
            args_dict["selected_evidence_ids"] = args_dict.pop("evidence_ids")
        if "selected_evidence_ids" not in args_dict and "selected_evidence_ids" in normalized:
            legacy_used = True
            args_dict["selected_evidence_ids"] = normalized.pop("selected_evidence_ids")
        if "answer_kind" not in args_dict:
            legacy_used = True
            args_dict["answer_kind"] = "knowledge_answer"
        normalized["arguments"] = args_dict

    # Normalize reason
    if "reason" not in normalized and "thought" in normalized:
        legacy_used = True
        normalized["reason"] = normalized.pop("thought")

    if legacy_used:
        warnings.warn(
            (
                "legacy Controller wire was normalized and is deprecated "
                f"({LEGACY_CONTROLLER_WIRE_PROTOCOL_VERSION}); remove compatibility "
                f"after {LEGACY_CONTROLLER_WIRE_REMOVAL_AFTER}"
            ),
            DeprecationWarning,
            stacklevel=2,
        )

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

    allowed_keys_map = {
        TOOL_CALL_ACTION: {"action", "tool", "arguments", "reason", "tool_call_id"},
        COMPOSE_ANSWER_ACTION: {"action", "arguments", "reason", "tool_call_id"},
        CLARIFY_ACTION: {"action", "arguments", "reason", "tool_call_id"},
        LIMITATION_ACTION: {"action", "arguments", "reason", "tool_call_id"},
        DIRECT_ANSWER_ACTION: {"action", "answer", "reason", "arguments", "tool_call_id"},
    }
    if action in allowed_keys_map:
        allowed_keys = allowed_keys_map[action]
        unexpected = sorted(k for k in normalized.keys() if k not in allowed_keys)
        if unexpected:
            raise ControllerOutputError(
                f"malformed_controller_wire: unexpected top-level property '{unexpected[0]}' for action '{action}'"
            )

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
                if eid not in state.selectable_evidence_ids:
                    raise ControllerOutputError(
                        f"malformed_compose_answer: selected evidence '{eid}' is not selectable"
                    )
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

    if action == LIMITATION_ACTION:
        if LIMITATION_ACTION not in state.available_control_actions:
            raise ValueError("malformed_decision_action: limitation is not currently available")
        raw_arguments = normalized.get("arguments")
        message = ""
        if isinstance(raw_arguments, Mapping):
            message = str(raw_arguments.get("message") or raw_arguments.get("answer") or "").strip()
        if not message and isinstance(normalized.get("message"), str):
            message = normalized["message"].strip()
        if not message and isinstance(normalized.get("answer"), str):
            message = normalized["answer"].strip()
        if not message:
            message = "当前知识库中未能检索到与该问题匹配的证据来源，无法给出带依据的结论。"
        return ControllerDecision(
            action=LIMITATION_ACTION,
            arguments={"message": message},
            reason=reason,
            tool_call_id=tool_call_id,
        )

    if action == CLARIFY_ACTION:
        if CLARIFY_ACTION not in state.available_control_actions:
            raise ValueError("malformed_decision_action: clarify is not currently available")
        raw_arguments = normalized.get("arguments")
        if raw_arguments not in (None, {}):
            raise ValueError("malformed_clarify: arguments must be an empty object")
        if "question" in normalized:
            raise ValueError("malformed_clarify: Controller must not generate clarification text")
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
        LIMITATION_ACTION,
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
                "arguments": dict(contracts[CLARIFY_ACTION].input_schema),
                "reason": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        })

    if LIMITATION_ACTION in controls:
        branches.append({
            "type": "object",
            "properties": {
                "action": {"const": LIMITATION_ACTION},
                "arguments": dict(contracts[LIMITATION_ACTION].input_schema),
                "reason": {"type": "string"},
            },
            "required": ["action", "arguments"],
            "additionalProperties": False,
        })

    if capability_schemas:
        for name, spec in capability_schemas.items():
            s = dict(spec)
            s.setdefault("type", "object")
            branches.append({
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
