"""Unit tests for GeoAI ContextFrame, ContextBudgetManager, and ContextEngine."""

from __future__ import annotations

import json
import pytest

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
