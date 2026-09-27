from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from app.models.search_models import DocumentResult
from app.services.agent.answer_generator import AnswerUnit, GeneratedAnswer
from app.services.agent.evidence import EvidenceLedger
from app.services.agent.model_client import ModelResponse
from app.services.agent.reviewer import GroundingReviewer
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.rag.contracts import RetrievalCandidate


def make_snapshot():
    result = DocumentResult(
        id="chunk-1",
        title="规划标准",
        content="重庆市滑坡监测应按本标准执行。",
        similarity=0.9,
        metadata={
            "chunk_id": "chunk-1",
            "document_name": "规划标准",
            "match_type": "keyword",
        },
        spatial_info=None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )
    ledger = EvidenceLedger(session_id="session-1")
    item = ledger.add_candidates(
        turn_id="turn-1",
        candidates=[RetrievalCandidate.from_document_result(result)],
    )[0]
    return ledger.freeze(turn_id="turn-1", evidence_ids=[item.evidence_id])


class FakeModelClient:
    def __init__(self, response: ModelResponse) -> None:
        self.response = response
        self.calls = []

    async def complete(self, request):
        self.calls.append(request)
        return self.response


@pytest.mark.asyncio
async def test_reviewer_checks_claims_against_frozen_evidence_with_reasoning_off() -> None:
    snapshot = make_snapshot()
    client = FakeModelClient(
        ModelResponse(
            content=(
                '{"verdict":"supported","findings":['
                '{"unit_id":"u1","status":"SUPPORTED","citations":["E1"]}'
                ']}'
            )
        )
    )
    reviewer = GroundingReviewer(model_client=client)

    result = await reviewer.review(
        question="重庆市滑坡监测有什么要求？",
        answer=GeneratedAnswer(
            kind="knowledge_answer",
            answer="应按本标准执行",
            citations=("E1",),
            units=(AnswerUnit(unit_id="u1", text="应按本标准执行", citations=("E1",)),),
        ),
        snapshot=snapshot,
        stage_policy=LLMStagePolicy(True, True),
    )

    assert result.verdict == "SUPPORTED"
    assert result.findings[0].status == "SUPPORTED"
    assert client.calls[0].stage == "reviewer"
    assert client.calls[0].request_reasoning is False
    schema = client.calls[0].response_schema
    assert schema is not None
    finding_schema = schema["properties"]["findings"]["items"]["properties"]
    assert finding_schema["unit_id"]["enum"] == ["u1"]
    assert finding_schema["citations"]["items"]["enum"] == ["E1"]


def test_reviewer_is_not_a_retrieval_or_planning_surface() -> None:
    assert not hasattr(GroundingReviewer, "retrieve")
    assert not hasattr(GroundingReviewer, "plan")


@pytest.mark.asyncio
async def test_reviewer_requires_exactly_one_review_per_answer_unit() -> None:
    snapshot = make_snapshot()

    class SequenceModelClient:
        def __init__(self) -> None:
            self.calls = []
            self.responses = [
                ModelResponse(
                    content=(
                        '{"verdict":"SUPPORTED","findings":['
                        '{"unit_id":"u1","status":"SUPPORTED","citations":["E1"]}'
                        ']}'
                    )
                ),
                ModelResponse(
                    content=(
                        '{"verdict":"SUPPORTED","findings":['
                        '{"unit_id":"u1","status":"SUPPORTED","citations":["E1"]},'
                        '{"unit_id":"u2","status":"SUPPORTED","citations":["E1"]}'
                        ']}'
                    )
                ),
            ]

        async def complete(self, request):
            self.calls.append(request)
            return self.responses.pop(0)

    client = SequenceModelClient()
    reviewer = GroundingReviewer(model_client=client)
    answer = GeneratedAnswer(
        kind="knowledge_answer",
        answer="第一点。\n第二点。",
        citations=("E1",),
        units=(
            AnswerUnit(unit_id="u1", text="第一点。", citations=("E1",)),
            AnswerUnit(unit_id="u2", text="第二点。", citations=("E1",)),
        ),
    )

    result = await reviewer.review(
        question="要求？",
        answer=answer,
        snapshot=snapshot,
        stage_policy=LLMStagePolicy(True, True),
        model_name="stable-main",
    )

    assert [finding.unit_id for finding in result.findings] == ["u1", "u2"]
    assert len(client.calls) == 2
    assert [call.model_name for call in client.calls] == ["stable-main", "stable-main"]


@pytest.mark.asyncio
async def test_supported_finding_must_preserve_answer_unit_citation_binding() -> None:
    snapshot = make_snapshot()
    second_item = replace(
        snapshot.items[0],
        evidence_id="evidence-2",
        citation_id="E2",
        chunk_id="chunk-2",
        content_hash="hash-2",
    )
    snapshot = replace(snapshot, items=(snapshot.items[0], second_item))
    client = FakeModelClient(
        ModelResponse(
            content=(
                '{"verdict":"SUPPORTED","findings":['
                '{"unit_id":"u1","status":"SUPPORTED","citations":["E2"]}'
                ']}'
            )
        )
    )
    reviewer = GroundingReviewer(model_client=client)

    with pytest.raises(ValueError, match="invalid structured output"):
        await reviewer.review(
            question="要求？",
            answer=GeneratedAnswer(
                kind="knowledge_answer",
                answer="应按本标准执行",
                citations=("E1",),
                units=(
                    AnswerUnit(
                        unit_id="u1",
                        text="应按本标准执行",
                        citations=("E1",),
                    ),
                ),
            ),
            snapshot=snapshot,
            stage_policy=LLMStagePolicy(False, False),
        )

    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_business_claim_cannot_be_supported_only_by_execution_receipt() -> None:
    snapshot = make_snapshot()
    receipt = replace(
        snapshot.items[0],
        source="browser_gis",
        evidence_class="EXECUTION_RECEIPT",
        support_scope="EXECUTION_CLAIM",
    )
    snapshot = replace(snapshot, items=(receipt,))
    client = FakeModelClient(
        ModelResponse(
            content=(
                '{"verdict":"SUPPORTED","findings":['
                '{"unit_id":"u1","status":"SUPPORTED","citations":["E1"]}'
                ']}'
            )
        )
    )
    reviewer = GroundingReviewer(model_client=client)

    with pytest.raises(ValueError, match="invalid structured output"):
        await reviewer.review(
            question="该业务事实成立吗？",
            answer=GeneratedAnswer(
                kind="knowledge_answer",
                answer="该业务事实成立",
                citations=("E1",),
                units=(
                    AnswerUnit(
                        unit_id="u1",
                        text="该业务事实成立",
                        citations=("E1",),
                    ),
                ),
            ),
            snapshot=snapshot,
            stage_policy=LLMStagePolicy(False, False),
        )

    assert len(client.calls) == 2
