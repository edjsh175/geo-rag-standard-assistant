from __future__ import annotations

from app.services.agent.stage_policy import LLMStagePolicy


def test_reasoning_policy_is_stage_specific() -> None:
    policy = LLMStagePolicy(
        user_thinking=True,
        endpoint_supports_reasoning=True,
    )

    assert policy.for_stage("controller").request_reasoning is True
    assert policy.for_stage("answer_generation").request_reasoning is False
    assert policy.for_stage("reviewer").request_reasoning is False


def test_controller_reasoning_requires_both_user_intent_and_endpoint_capability() -> None:
    assert LLMStagePolicy(
        user_thinking=False,
        endpoint_supports_reasoning=True,
    ).for_stage("controller").request_reasoning is False
    assert LLMStagePolicy(
        user_thinking=True,
        endpoint_supports_reasoning=False,
    ).for_stage("controller").request_reasoning is False


def test_answer_and_reviewer_reasoning_stay_off_even_when_user_thinking_is_on() -> None:
    policy = LLMStagePolicy(
        user_thinking=True,
        endpoint_supports_reasoning=True,
    )

    assert policy.for_stage("answer_generation").request_reasoning is False
    assert policy.for_stage("reviewer").request_reasoning is False
