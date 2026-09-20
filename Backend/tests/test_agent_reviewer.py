from __future__ import annotations

from datetime import datetime

import pytest

from app.models.search_models import DocumentResult
from app.services.agent.answer_generator import GeneratedAnswer
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
                '{"claim":"应按本标准执行","status":"SUPPORTED","citations":["E1"]}'
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
        ),
        snapshot=snapshot,
        stage_policy=LLMStagePolicy(True, True),
    )

    assert result.verdict == "SUPPORTED"
    assert result.findings[0].status == "SUPPORTED"
    assert client.calls[0].stage == "reviewer"
    assert client.calls[0].request_reasoning is False


def test_reviewer_is_not_a_retrieval_or_planning_surface() -> None:
    assert not hasattr(GroundingReviewer, "retrieve")
    assert not hasattr(GroundingReviewer, "plan")
