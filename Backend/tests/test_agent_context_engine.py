"""Unit tests for GeoAI ContextFrame, ContextBudgetManager, and ContextEngine."""

from __future__ import annotations

import json
import inspect
import pytest

from app.services.agent.context.frame import _thaw
from app.services.agent.context.budget import (
    CharWeightedTokenEstimator,
    ContextBudgetConfig,
    ContextBudgetManager,
    StageBudget,
)
from app.services.agent.context.engine import ContextEngine
from app.services.agent.context.frame import ContextFrame
from app.services.agent.events import AgentEvent


def test_char_weighted_token_estimator():
    estimator = CharWeightedTokenEstimator()
    assert estimator.estimate("") == 0
    # 20 ASCII chars -> ~5 tokens
    assert estimator.estimate("12345678901234567890") == 5
    # 3 Chinese chars -> ~2 tokens
    assert estimator.estimate("城市规划") == 2
    # mixed
    assert estimator.estimate("GeoAI 空间规划") > 0


def test_context_frame_immutability():
    frame = ContextFrame.create(
        session={"session_id": "s-1"},
        user_question="查看规划图层",
        spatial={"bbox": [120.0, 30.0, 121.0, 31.0]},
        conversation=[{"role": "user", "text": "你好"}],
        source_event_ids=["ev-1", "ev-2"],
    )
    assert frame.user_question == "查看规划图层"
    assert frame.session["session_id"] == "s-1"
    assert frame.source_event_ids == ("ev-1", "ev-2")

    # to_dict roundtrip
    d = frame.to_dict()
    assert d["session"]["session_id"] == "s-1"
    assert len(d["conversation"]) == 1


def test_context_frame_preserves_authority_classes_without_promoting_client_hints():
    engine = ContextEngine()
    frame = engine.build_frame(
        session_id="session-authority",
        principal_id="admin:test",
        question="这个文档讲什么？",
        events=(),
        working_evidence=(),
        spatial_context={"zoom": 10},
        metadata={
            "user_ui_selections": {
                "document": {"document_id": "14741", "title": "权威标题"}
            },
            "client_hints": {
                "document_selection": {"document_id": "untrusted", "admission_status": "rejected"}
            },
        },
        current_turn_id="turn-1",
    )

    payload = frame.to_dict()
    assert payload["user_ui_selections"]["document"]["document_id"] == "14741"
    assert payload["client_hints"]["document_selection"]["document_id"] == "untrusted"
    assert "client_hints" not in payload["runtime_facts"]
    assert "user_ui_selections" not in payload["runtime_facts"]

    projection, _ = engine.project_for_controller(
        frame,
        tool_contracts_text="",
        tool_names="",
    )
    assert projection.user_ui_selections["document"]["document_id"] == "14741"
    assert projection.client_hints["document_selection"]["document_id"] == "untrusted"


def test_budget_manager_controller_trimming():
    # Configure tight controller budget: 200 tokens available
    config = ContextBudgetConfig(
        controller=StageBudget(max_tokens=400, system_reserve=100, generation_reserve=100)
    )
    manager = ContextBudgetManager(config=config)

    # 10 lines of long conversation
    conv_lines = [f"user: 历史问题第{i}轮很多长文本" * 5 for i in range(10)]
    evidence = [
        {"score": 0.5, "title": "low score doc", "text": "text1"},
        {"score": 0.95, "title": "high score doc", "text": "text2"},
    ]
    map_ctx = {
        "bbox": [100, 20, 105, 25],
        "features": [{"id": f"feat-{i}", "geom": "point"} for i in range(20)],
    }

    summary, trimmed_ev, trimmed_map, tokens = manager.trim_controller_context(
        question="最新城市空间分析",
        conversation_lines=conv_lines,
        working_evidence=evidence,
        map_context=map_ctx,
        tool_contracts_text="tool search_spatial: search coordinates",
    )

    # Historical conversation should be pruned to keep most recent lines
    assert len(summary.split("\n")) < len(conv_lines)
    # High score evidence preserved first
    assert any(e["score"] == 0.95 for e in trimmed_ev)
    # Map features should be compacted
    assert trimmed_map is not None
    assert trimmed_map.get("_features_truncated") is True
    assert len(trimmed_map.get("features", [])) <= 3


def test_budget_manager_preserves_map_context_v2_execution_state_when_compacting():
    config = ContextBudgetConfig(
        controller=StageBudget(max_tokens=900, system_reserve=100, generation_reserve=100)
    )
    manager = ContextBudgetManager(config=config)
    target_layer_ref = "ul-99"
    target_file_ref = "vf-99"
    map_ctx = {
        "schema_version": 2,
        "dimension": "2d",
        "ready": True,
        "revision": 42,
        "supported_tools": [
            "locate_map",
            "set_layer_visibility",
            "import_vector_dataset",
            "set_vector_style",
            "fit_vector_layer",
            "inspect_layer_features",
            "get_feature_geometry",
        ],
        "viewport": {"center": [104.0, 30.0], "zoom": 9, "crs": "EPSG:4326"},
        "active_region": {"adcode": "510100", "name": "成都市"},
        "layer_tree": [
            {
                "layer_ref": f"ul-{i}",
                "name": f"图层-{i}",
                "kind": "user_vector",
                "visible": True,
                "opacity": 1.0,
                "z_index": i,
            }
            for i in range(120)
        ],
        "user_layers": [
            {
                "layer_ref": f"ul-{i}",
                "name": f"用户图层-{i}",
                "geometry_types": ["Polygon"],
                "feature_count": 200,
                "feature_refs": [f"feat-{i}-{j}" for j in range(30)],
                "visible": True,
                "style": {
                    "stroke": {"color": "#ff0000", "width": 2, "opacity": 1},
                    "fill": {"color": "#ffcccc", "opacity": 0.4},
                    "radius": 5,
                },
            }
            for i in range(120)
        ],
        "available_files": [
            {
                "file_ref": f"vf-{i}",
                "name": f"数据-{i}",
                "format": "geojson",
                "parts": [f"part-{j}" for j in range(12)],
            }
            for i in range(120)
        ],
    }

    _, _, projected_map, tokens = manager.trim_controller_context(
        question=f"请处理 layer_ref={target_layer_ref} 并导入 file_ref={target_file_ref}",
        conversation_lines=(),
        working_evidence=(),
        map_context=map_ctx,
        tool_contracts_text="",
    )

    assert projected_map is not None
    assert projected_map["schema_version"] == 2
    assert projected_map["dimension"] == "2d"
    assert projected_map["ready"] is True
    assert projected_map["revision"] == 42
    assert projected_map["supported_tools"] == map_ctx["supported_tools"]
    assert projected_map["viewport"] == map_ctx["viewport"]
    assert projected_map["active_region"] == map_ctx["active_region"]
    assert any(item["layer_ref"] == target_layer_ref for item in projected_map["layer_tree"])
    assert any(item["layer_ref"] == target_layer_ref for item in projected_map["user_layers"])
    assert any(item["file_ref"] == target_file_ref for item in projected_map["available_files"])
    projection_meta = projected_map["_projection"]
    assert projection_meta["truncated"] is True
    assert projection_meta["layer_tree"]["total_count"] == 120
    assert projection_meta["user_layers"]["total_count"] == 120
    assert projection_meta["available_files"]["total_count"] == 120
    assert projection_meta["layer_tree"]["projected_count"] < 120
    assert projection_meta["user_layers"]["projected_count"] < 120
    assert projection_meta["available_files"]["projected_count"] < 120
    assert tokens <= config.controller.available_context_tokens


def test_context_engine_projections_and_snapshots():
    engine = ContextEngine()
    events = [
        AgentEvent(
            event_type="user_message",
            session_id="sess-100",
            turn_id="turn-1",
            payload={"text": "请显示西湖区的控制性详细规划"},
            event_id="ev-101",
        ),
        AgentEvent(
            event_type="assistant_message",
            session_id="sess-100",
            turn_id="turn-1",
            payload={"text": "已为您检索到西湖区控规文件"},
            event_id="ev-102",
        ),
    ]

    frame = engine.build_frame(
        session_id="sess-100",
        principal_id="user-42",
        question="西湖区绿地率要求是多少？",
        events=events,
        working_evidence=[{
            "citation_id": "E1",
            "score": 0.92,
            "title": "西湖区规划标准",
            "text": "新建居住区绿地率不低于35%",
        }],
        spatial_context={"bbox": [120.1, 30.2, 120.2, 30.3]},
    )

    assert frame.user_question == "西湖区绿地率要求是多少？"
    assert len(frame.conversation) == 2
    assert frame.source_event_ids == ("ev-101", "ev-102")

    # Controller projection
    proj_ctrl, snap_ctrl = engine.project_for_controller(
        frame,
        tool_contracts_text="tool: search_spatial",
        tool_names="search_spatial",
    )
    assert proj_ctrl.user_question == frame.user_question
    assert snap_ctrl.stage == "controller"
    assert snap_ctrl.frame_hash != ""
    assert snap_ctrl.projection_hash != ""
    assert len(snap_ctrl.sections) >= 5

    # Answer projection
    proj_ans, snap_ans = engine.project_for_answer(
        frame,
        conversation_summary=proj_ctrl.conversation_text,
    )
    assert proj_ans.user_question == frame.user_question
    assert snap_ans.stage == "answer"
    assert len(proj_ans.citable_evidence) == 1

    # Reviewer projection
    proj_rev, snap_rev = engine.project_for_reviewer(
        frame,
        draft_answer="西湖区绿地率不低于35% [E1]。",
    )
    assert proj_rev.draft_answer == "西湖区绿地率不低于35% [E1]。"
    assert snap_rev.stage == "reviewer"


def test_context_engine_keeps_evidence_structured_outside_conversation_text():
    engine = ContextEngine()
    frame = engine.build_frame(
        session_id="sess-structured-evidence",
        principal_id="user-1",
        question="问题",
        events=(),
        working_evidence=(
            {
                "evidence_id": "ev-1",
                "citation_id": "E1",
                "title": "标准",
                "excerpt": "证据正文",
            },
        ),
        current_turn_id="turn-1",
    )

    projection, _ = engine.project_for_controller(
        frame,
        tool_contracts_text="",
        tool_names="",
    )

    assert "ev-1" not in projection.conversation_text
    assert projection.working_evidence[0]["evidence_id"] == "ev-1"
    assert projection.evidence_catalog[0]["citation_id"] == "E1"


def test_context_snapshot_deterministic_hash():
    engine = ContextEngine()
    frame = engine.build_frame(
        session_id="sess-1",
        principal_id="user-1",
        question="查询杭州市总体规划",
        events=[],
        working_evidence=[],
    )

    _, snap1 = engine.project_for_controller(
        frame,
        tool_contracts_text="tools",
        tool_names="toolA",
    )
    _, snap2 = engine.project_for_controller(
        frame,
        tool_contracts_text="tools",
        tool_names="toolA",
    )

    # Identical inputs must yield identical hashes for audit reproducibility
    assert snap1.frame_hash == snap2.frame_hash
    assert snap1.projection_hash == snap2.projection_hash


def test_answer_and_reviewer_snapshots_use_server_owned_current_turn_id():
    engine = ContextEngine()
    events = [
        AgentEvent(
            event_type="user_message",
            session_id="sess-turn",
            turn_id="turn-1",
            payload={"text": "上一轮"},
            event_id="ev-turn-1",
        ),
        AgentEvent(
            event_type="assistant_message",
            session_id="sess-turn",
            turn_id="turn-1",
            payload={"text": "上一轮回答"},
            event_id="ev-turn-2",
        ),
        AgentEvent(
            event_type="user_message",
            session_id="sess-turn",
            turn_id="turn-2",
            payload={"text": "当前问题"},
            event_id="ev-turn-3",
        ),
    ]
    frame = engine.build_frame(
        session_id="sess-turn",
        principal_id="user-turn",
        question="当前问题",
        events=events,
        current_turn_id="turn-2",
        working_evidence=[],
    )

    _, answer_snapshot = engine.project_for_answer(frame, conversation_summary="上一轮摘要")
    _, reviewer_snapshot = engine.project_for_reviewer(frame, draft_answer="候选答案")

    assert answer_snapshot.turn_id == "turn-2"
    assert reviewer_snapshot.turn_id == "turn-2"


def test_context_engine_scopes_runtime_facts_to_explicit_current_and_previous_turns():
    assert "current_turn_id" in inspect.signature(ContextEngine.build_frame).parameters

    events = [
        AgentEvent("user_message", "sess-scope", "turn-old", payload={"text": "查滑坡标准"}, event_id="old-user"),
        AgentEvent("controller_decision", "sess-scope", "turn-old", payload={"tool_name": "retrieve_kb"}, event_id="old-decision"),
        AgentEvent("tool_started", "sess-scope", "turn-old", payload={"tool_name": "retrieve_kb", "tool_call_id": "old-call"}, event_id="old-start"),
        AgentEvent("tool_completed", "sess-scope", "turn-old", payload={"tool_name": "retrieve_kb", "tool_call_id": "old-call", "status": "succeeded"}, event_id="old-complete"),
        AgentEvent("assistant_message", "sess-scope", "turn-old", payload={"text": "找到滑坡标准"}, event_id="old-assistant"),
        AgentEvent("user_message", "sess-scope", "turn-current", payload={"text": "查规划标准空间数据要求"}, event_id="current-user"),
    ]

    frame = ContextEngine().build_frame(
        session_id="sess-scope",
        principal_id="user-scope",
        question="查规划标准空间数据要求",
        events=events,
        current_turn_id="turn-current",
        working_evidence=[],
        evidence_memory=[],
        metadata={"current_turn": {"turn_id": "spoofed", "tool_calls": [{"tool": "retrieve_kb"}]}},
    )

    runtime_facts = _thaw(frame.runtime_facts)
    assert runtime_facts["current_turn"] == {
        "turn_id": "turn-current",
        "controller_actions": [],
        "tool_calls": [],
        "clarification": None,
        "publication_state": None,
        "review_verdict": None,
        "map_facts": [],
    }
    assert runtime_facts["previous_turn"]["turn_id"] == "turn-old"
    assert runtime_facts["previous_turn"]["tool_calls"] == [
        {"tool": "retrieve_kb", "status": "succeeded", "call_id": "old-call"}
    ]
    assert "查规划标准空间数据要求" not in [message["text"] for message in frame.conversation]
    assert frame.source_event_ids[-1] == "current-user"

    _, snapshot = ContextEngine().project_for_controller(
        frame, tool_contracts_text="", tool_names=""
    )
    assert snapshot.turn_id == "turn-current"


def test_context_engine_keeps_current_turn_completion_event_in_runtime_facts():
    events = [
        AgentEvent("user_message", "sess-current", "turn-current", payload={"text": "查标准"}, event_id="current-user"),
        AgentEvent("controller_decision", "sess-current", "turn-current", payload={"tool_name": "retrieve_kb"}, event_id="decision"),
        AgentEvent("tool_started", "sess-current", "turn-current", payload={"tool_name": "retrieve_kb", "tool_call_id": "call-1"}, event_id="started"),
        AgentEvent("tool_completed", "sess-current", "turn-current", payload={"tool_name": "retrieve_kb", "tool_call_id": "call-1", "status": "succeeded"}, event_id="completed"),
    ]
    frame = ContextEngine().build_frame(
        session_id="sess-current",
        principal_id="user-current",
        question="查标准",
        events=events,
        current_turn_id="turn-current",
        working_evidence=[],
    )

    assert _thaw(frame.runtime_facts)["current_turn"]["tool_calls"] == [
        {"tool": "retrieve_kb", "status": "succeeded", "call_id": "call-1"}
    ]
