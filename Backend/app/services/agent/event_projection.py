"""Finite, UI-safe projections for Agent runtime facts."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_SAFE_ERROR_MESSAGES = {
    "TOOL_FAILED": "工具执行失败。",
    "TOOL_INVALID_ARGUMENTS": "工具输入未通过校验。",
    "TOOL_UNAVAILABLE": "工具当前不可用。",
    "TOOL_TIMEOUT": "工具执行超时。",
    "REVIEW_FAILED": "证据审查执行失败。",
    "REPAIR_MODEL_FAILED": "答案修复模型执行失败。",
    "REPAIR_PROTOCOL_INVALID": "答案修复输出未满足结构化协议。",
    "REPAIR_CONTRACT_VIOLATION": "答案修复结果违反修复契约。",
    "REVIEW2_FAILED": "第二轮证据审查执行失败。",
    "REVIEW2_REJECTED": "修复后的答案未通过第二轮证据审查。",
}


def safe_error(code: str) -> dict[str, str]:
    normalized = code if code in _SAFE_ERROR_MESSAGES else "TOOL_FAILED"
    return {"code": normalized, "message": _SAFE_ERROR_MESSAGES[normalized]}


def browser_receipt_summary(receipt: Mapping[str, Any]) -> dict[str, Any]:
    effect = receipt.get("effect") if isinstance(receipt.get("effect"), Mapping) else {}
    context = receipt.get("map_context") if isinstance(receipt.get("map_context"), Mapping) else {}
    summary: dict[str, Any] = {}
    effect_status = effect.get("effect_status", effect.get("status"))
    revision = effect.get("state_revision", context.get("state_revision", context.get("revision")))
    dimension = context.get("map_dimension", context.get("dimension"))
    if isinstance(effect_status, str) and len(effect_status) <= 40:
        summary["effect_status"] = effect_status
    if isinstance(revision, (str, int)) and not isinstance(revision, bool):
        summary["state_revision"] = revision
    if isinstance(dimension, str) and len(dimension) <= 20:
        summary["map_dimension"] = dimension
    return summary


def tool_result_summary(tool_name: str, observation: Any) -> dict[str, Any]:
    """Summarize only stable identifiers and counts from a real observation."""
    payload = observation.payload if isinstance(observation.payload, Mapping) else {}
    summary: dict[str, Any] = {}
    for ids_key in ("evidence_ids", "selected_evidence_ids", "result_ids", "feature_ids", "layer_ids"):
        values = payload.get(ids_key)
        if isinstance(values, (list, tuple)):
            key = "evidence_ids" if "evidence" in ids_key else ids_key
            safe_values = [str(value)[:128] for value in values[:50] if isinstance(value, (str, int))]
            summary[key] = safe_values
            count_key = "evidence_count" if key == "evidence_ids" else f"{key.removesuffix('_ids')}_count"
            summary[count_key] = len(values)
    for count_key in ("candidate_count", "admitted_count", "match_count", "result_count", "feature_count", "layer_count"):
        value = payload.get(count_key)
        if isinstance(value, int) and not isinstance(value, bool):
            summary[count_key] = max(0, value)
    if observation.status == "browser_execution_required":
        summary["browser_handoff"] = "pending"
    if observation.status in {"failed", "denied"}:
        summary["error"] = safe_error("TOOL_INVALID_ARGUMENTS" if observation.status == "denied" else "TOOL_FAILED")
    return summary


_PUBLIC_PAYLOAD_FIELDS = {
    "user_message": {"text"},
    "controller_decision": {"tool_name", "tool_call_id", "action", "reason_code"},
    "tool_started": {"tool_name", "tool_call_id", "arguments"},
    "tool_completed": {"tool_name", "tool_call_id", "status", "result_summary", "error"},
    "browser_tool_requested": {"tool_name", "tool_call_id", "arguments"},
    "browser_tool_completed": {"tool_name", "tool_call_id", "status", "receipt", "error"},
    "browser_tool_cancelled": {"tool_name", "tool_call_id", "reason"},
    "evidence_frozen": {"snapshot_id", "evidence_ids", "selected_evidence_ids", "selected_count", "citation_count"},
    "answer_generated": {"kind", "citations"},
    "review_started": {"review_id", "attempt"},
    "review_completed": {"review_id", "attempt", "verdict", "finding_count", "reason_code", "error"},
    "answer_repair_completed": {"outcome", "error"},
    "publication_completed": {"state", "publication_state", "reason_code"},
    "assistant_message": {"text"},
    "run_cancel_requested": {"reason"},
    "run_cancelled": {"reason"},
}


def public_event_payload(event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project stored facts to finite frontend fields; never expose arbitrary errors/data."""
    allowed = _PUBLIC_PAYLOAD_FIELDS.get(event_type)
    if allowed is None:
        return {}
    output = {key: payload[key] for key in allowed if key in payload}
    if event_type in {"tool_started", "browser_tool_requested"}:
        arguments = output.get("arguments")
        tool_name = str(output.get("tool_name") or "")
        tool_argument_fields = {
            "retrieve_kb": {"query"}, "reuse_evidence": {"query", "limit"},
            "search_evidence_memory": {"query", "limit"},
            "import_vector_dataset": {"file_ref", "name"},
            "set_layer_visibility": {"layer_ref", "visible"},
            "set_vector_style": {"layer_ref", "style"},
            "fit_vector_layer": {"layer_ref"}, "locate_map": {"longitude", "latitude", "zoom"},
            "inspect_layer_features": {"layer_ref", "offset", "limit"},
            "get_feature_geometry": {"feature_ref"},
            "query_spatial_relation": {"left", "right", "relation"},
            "spatial_overlay": {"left", "right", "operation"},
            "create_buffer": {"center", "distance_m"},
            "render_geojson_layer": {"geojson", "name", "style"},
            "query_geospatial_data": {"operation", "target_table", "select_fields", "filters", "spatial", "limit"},
        }
        allowed_args = tool_argument_fields.get(tool_name, set())
        safe_args: dict[str, Any] = {}
        if isinstance(arguments, Mapping):
            for key in allowed_args:
                if key not in arguments:
                    continue
                value = arguments[key]
                if isinstance(value, str):
                    safe_args[key] = value[:2000]
                elif isinstance(value, (str, int, float, bool)) or value is None:
                    safe_args[key] = value
                elif isinstance(value, list):
                    if key == "filters":
                        safe_args[key] = [
                            _scalar_fields(item, {"field", "operator", "value"})
                            for item in value[:20]
                            if isinstance(item, Mapping)
                        ]
                    else:
                        safe_args[key] = value[:50]
                elif isinstance(value, Mapping):
                    if key == 'style':
                        safe_args[key] = {
                            name: _scalar_fields(value[name], fields)
                            for name, fields in {'stroke': {'color', 'width', 'opacity'}, 'fill': {'color', 'opacity'}}.items()
                            if isinstance(value.get(name), Mapping)
                        }
                        safe_args[key].update(_scalar_fields(value, {'radius'}))
                    elif key == 'geojson':
                        safe_args[key] = _scalar_fields(value, {'type'})
                    elif key == 'spatial':
                        spatial = _scalar_fields(value, {'distance_m'})
                        if isinstance(value.get('geometry'), Mapping):
                            spatial['geometry'] = _scalar_fields(value['geometry'], {'type'})
                        safe_args[key] = spatial
                    elif key in {'left', 'right'}:
                        operand = {}
                        if isinstance(value.get('region'), Mapping):
                            operand['region'] = _scalar_fields(value['region'], {'adcode', 'region_name'})
                        if isinstance(value.get('geometry'), Mapping):
                            # Coordinates can be large; the UI needs the operand kind, not the raw geometry.
                            operand['geometry'] = _scalar_fields(value['geometry'], {'type'})
                        safe_args[key] = operand
        output["arguments"] = safe_args
    if event_type == "tool_completed":
        if "error" in output:
            output["error"] = safe_error(str(output["error"].get("code", "TOOL_FAILED")) if isinstance(output["error"], Mapping) else "TOOL_FAILED")
        if not isinstance(output.get("result_summary"), Mapping):
            output["result_summary"] = {}
    if event_type == "browser_tool_completed":
        receipt = output.get("receipt")
        if isinstance(receipt, Mapping):
            output["receipt"] = {
                key: receipt[key] for key in ("effect_status", "state_revision", "map_dimension") if key in receipt
            }
        if "error" in output:
            output["error"] = safe_error("TOOL_FAILED")
    if event_type == "review_completed" and "error" in output:
        raw_error = output["error"]
        code = (
            str(raw_error.get("code") or "REVIEW_FAILED")
            if isinstance(raw_error, Mapping)
            else "REVIEW_FAILED"
        )
        if code not in {"REVIEW_FAILED", "REVIEW2_FAILED"}:
            code = "REVIEW_FAILED"
        output["error"] = safe_error(code)
    if event_type == "answer_repair_completed" and "error" in output:
        raw_error = output["error"]
        code = (
            str(raw_error.get("code") or "REPAIR_MODEL_FAILED")
            if isinstance(raw_error, Mapping)
            else "REPAIR_MODEL_FAILED"
        )
        if code not in {
            "REPAIR_MODEL_FAILED",
            "REPAIR_PROTOCOL_INVALID",
            "REPAIR_CONTRACT_VIOLATION",
            "REVIEW2_FAILED",
            "REVIEW2_REJECTED",
        }:
            code = "REPAIR_MODEL_FAILED"
        output["error"] = safe_error(code)
    return output


def is_public_event(event_type: str) -> bool:
    return event_type in _PUBLIC_PAYLOAD_FIELDS


def _scalar_fields(value: Mapping[str, Any], fields: set[str]) -> dict[str, Any]:
    return {
        key: (entry[:2000] if isinstance(entry, str) else entry)
        for key in fields if key in value
        for entry in [value[key]]
        if isinstance(entry, (str, int, float, bool)) or entry is None
    }
