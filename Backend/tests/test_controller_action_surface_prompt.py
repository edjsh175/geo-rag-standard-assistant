from __future__ import annotations

import pytest

from app.services.agent.controller import MainController
from app.services.agent.controller_protocol import ExecutableActionState
from app.services.agent.model_client import ModelResponse
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.tool_runtime import ToolObservation
from app.services.agent.tools import build_default_tool_registry


class CapturingModelClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return ModelResponse(content=self.response)


def _controller_with_action_state(
    *, identity_status: str, response: str, selectable_evidence_ids=()
):
    registry = build_default_tool_registry()
    state = ExecutableActionState.compute(
        registry=registry,
        identity_status=identity_status,
        selectable_evidence_ids=selectable_evidence_ids,
    )
    client = CapturingModelClient(response)
    controller = MainController(model_client=client, tool_registry=registry)
    return controller, client, state


async def _capture_prompt(
    controller,
    client,
    state,
    *,
    question: str = "Query two related standard facts at once.",
    context_summary: str = "",
    observations=(),
    working_evidence=(),
) -> str:
    await controller.decide(
        action_state=state,
        stage_policy=LLMStagePolicy(user_thinking=False, endpoint_supports_reasoning=False),
        question=question,
        context_summary=context_summary,
        working_evidence=working_evidence,
        observations=observations,
    )
    return client.requests[0].messages[0]["content"]


@pytest.mark.asyncio
async def test_clarify_instructions_match_current_action_space() -> None:
    retrieve_response = '{"action":"tool_call","tool":"retrieve_kb","arguments":{"query":"Query two related standard facts"}}'
    controller, client, state = _controller_with_action_state(
        identity_status="resolved", response=retrieve_response
    )
    prompt_without_clarify = await _capture_prompt(controller, client, state)

    assert "- When the user's query asks for clarification" not in prompt_without_clarify
    assert '{"action":"clarify"' not in prompt_without_clarify
    assert "Choose exactly one action from the current Action Space" in prompt_without_clarify

    controller, client, state = _controller_with_action_state(
        identity_status="ambiguous",
        response='{"action":"clarify","arguments":{"question":"Please specify the standard topic."}}',
    )
    prompt_with_clarify = await _capture_prompt(controller, client, state)

    assert '{"action":"clarify"' in prompt_with_clarify
    assert "When the user's query asks for clarification" in prompt_with_clarify


@pytest.mark.asyncio
async def test_controller_prompt_guides_underspecified_knowledge_retrieval_and_schema_correct_spatial_query() -> None:
    response = '{"action":"tool_call","tool":"retrieve_kb","arguments":{"query":"Query two related standard facts"}}'
    controller, client, state = _controller_with_action_state(
        identity_status="resolved", response=response
    )
    prompt = await _capture_prompt(controller, client, state)

    assert "search with retrieve_kb using the user's request and existing conversation topics" in prompt
    assert "Do not invent a standard topic" in prompt
    assert "covering all requested facts" in prompt
    assert 'left={"geometry": geometry}, right={"region":{"region_name":"鎴愰兘甯?}}' in prompt
    assert "automated evaluators" not in prompt
    assert "鐩存帴璇存槑澶辫触銆佸師鍥犲拰宸茶娴嬬姸鎬? in prompt


@pytest.mark.asyncio
async def test_current_turn_observations_bound_specific_and_repeated_reads() -> None:
    response = '{"action":"direct_answer","answer":"The requested read is complete."}'
    controller, client, state = _controller_with_action_state(
        identity_status="resolved", response=response
    )
    previous_turn_context = "A prior turn read feature uf_current successfully."
    no_current_read_prompt = await _capture_prompt(
        controller,
        client,
        state,
        question='Read feature_ref="uf_current" again and compare the reads.',
        context_summary=previous_turn_context,
    )

    assert "current-turn Observations" in no_current_read_prompt
    assert "Historical context or prior-turn reads do not satisfy a requested read" in no_current_read_prompt
    assert "call get_feature_geometry for the requested feature_ref" in no_current_read_prompt

    one_read = ToolObservation(
        tool_call_id="read-1",
        tool_name="get_feature_geometry",
        status="succeeded",
        payload={"feature_ref": "uf_current", "geometry": {"type": "Point", "coordinates": [1, 2]}},
    )
    controller, client, state = _controller_with_action_state(
        identity_status="resolved", response=response
    )
    one_read_prompt = await _capture_prompt(
        controller,
        client,
        state,
        question='Read feature_ref="uf_current" again and compare the reads.',
        observations=(one_read,),
    )
    assert "get_feature_geometry" in client.requests[0].messages[1]["content"]
    assert "uf_current" in client.requests[0].messages[1]["content"]
    assert "for a repeated read, obtain exactly two successful current-turn reads" in one_read_prompt.lower()
    assert "continue any other requested steps" in one_read_prompt.lower()

    second_read = ToolObservation(
        tool_call_id="read-2",
        tool_name="get_feature_geometry",
        status="succeeded",
        payload={"feature_ref": "uf_current", "geometry": {"type": "Point", "coordinates": [1, 2]}},
    )
    controller, client, state = _controller_with_action_state(
        identity_status="resolved", response=response
    )
    two_reads_prompt = await _capture_prompt(
        controller,
        client,
        state,
        question='Read feature_ref="uf_current" again and compare the reads.',
        observations=(one_read, second_read),
    )
    assert "uf_current" in client.requests[0].messages[1]["content"]
    assert "compare the feature refs and geometry values" in two_reads_prompt.lower()
    assert "provide the comparison and continue any other requested steps" in two_reads_prompt.lower()
    assert "finalize only when the full user request is satisfied" in two_reads_prompt.lower()


@pytest.mark.asyncio
async def test_completed_geometry_read_continues_remaining_spatial_relation_step() -> None:
    controller, client, state = _controller_with_action_state(
        identity_status="resolved",
        response='{"action":"direct_answer","answer":"The request has been handled."}',
    )
    geometry_observation = ToolObservation(
        tool_call_id="geometry-1",
        tool_name="get_feature_geometry",
        status="succeeded",
        payload={"feature_ref": "uf_current", "geometry": {"type": "Point", "coordinates": [1, 2]}},
    )
    prompt = await _capture_prompt(
        controller,
        client,
        state,
        question='Read feature_ref="uf_current" geometry and check whether it is within Chengdu.',
        observations=(geometry_observation,),
    )

    assert "satisfies only that read substep" in prompt.lower()
    assert "continue remaining requested steps" in prompt.lower()
    assert "query_spatial_relation" in prompt
    assert "finalize only when the full user request is satisfied" in prompt.lower()


@pytest.mark.asyncio
async def test_pagination_observation_must_match_requested_offset_and_limit() -> None:
    controller, client, state = _controller_with_action_state(
        identity_status="resolved",
        response='{"action":"direct_answer","answer":"The request has been handled."}',
    )
    first_page = ToolObservation(
        tool_call_id="page-1",
        tool_name="inspect_layer_features",
        status="succeeded",
        payload={"layer_ref": "ul_current", "offset": 0, "limit": 20, "features": []},
    )
    prompt = await _capture_prompt(
        controller,
        client,
        state,
        question='Read the next batch from layer_ref="ul_current" with offset=20 and limit=20.',
        observations=(first_page,),
    )

    assert "matching the tool, reference, and all requested parameters" in prompt.lower()
    assert "offset=0 does not satisfy a request for offset=20" in prompt.lower()
    assert "continue remaining requested steps" in prompt.lower()


@pytest.mark.asyncio
async def test_failure_response_wording_uses_direct_failure_language() -> None:
    controller, client, state = _controller_with_action_state(
        identity_status="resolved",
        response='{"action":"direct_answer","answer":"鎿嶄綔澶辫触锛屽凡涓銆?}',
    )
    prompt = await _capture_prompt(controller, client, state)

    assert "澶辫触鍥炲涓笉寰楀嚭鐜扳€滄垚鍔熲€濇垨鈥滃凡瀹屾垚鈥? in prompt
    assert "鐩存帴璇存槑澶辫触銆佸師鍥犲拰宸茶娴嬬姸鎬? in prompt
    assert "鍖呮嫭鍚﹀畾鍙ャ€佸亣璁炬垨鏈潵鎴愬姛鎻忚堪" in prompt


@pytest.mark.asyncio
async def test_unmatched_historical_evidence_requires_current_question_retrieval() -> None:
    historical_evidence = {
        "evidence_id": "ev-old-topic",
        "citation_id": "E-OLD",
        "title": "闄嶉洦棰勮闃堝€?,
        "excerpt": "鍘嗗彶涓婚涓殑闄嶉洦棰勮鐩稿叧鍐呭銆?,
    }
    controller, client, state = _controller_with_action_state(
        identity_status="resolved",
        response='{"action":"tool_call","tool":"retrieve_kb","arguments":{"query":"鏌ヨ瑙勫垝鏍囧噯涓殑绌洪棿鏁版嵁瑕佹眰"}}',
        selectable_evidence_ids=(historical_evidence["evidence_id"],),
    )
    prompt = await _capture_prompt(
        controller,
        client,
        state,
        question="鏌ヨ瑙勫垝鏍囧噯涓殑绌洪棿鏁版嵁瑕佹眰銆?,
        context_summary="Earlier discussion covered rainfall warning thresholds.",
        working_evidence=(historical_evidence,),
    )

    assert "an evidence gap for the current question, not proof that the knowledge base has no data" in prompt.lower()
    assert "call retrieve_kb for the current question before concluding there is no supporting knowledge" in prompt.lower()
    assert "use limitation for a fact-seeking knowledge request only after a current-turn retrieval returns no relevant matches or the tool reports failure/unavailability" in prompt.lower()
    assert "cite unrelated evidence" in prompt.lower()
    assert "explicitly asks about system limitations, explain the known policy without implying a search occurred" in prompt.lower()
