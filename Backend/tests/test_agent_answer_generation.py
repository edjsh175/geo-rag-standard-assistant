from __future__ import annotations

from datetime import datetime

import pytest

from app.models.search_models import DocumentResult
from app.services.agent.answer_generator import (
    AnswerGenerationError,
    AnswerGenerator,
)
from app.services.agent.evidence import EvidenceLedger
from app.services.agent.model_client import ModelResponse
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
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.calls = []

    async def complete(self, request):
        self.calls.append(request)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_knowledge_answer_requires_non_empty_frozen_evidence() -> None:
    client = FakeModelClient([])
    generator = AnswerGenerator(model_client=client)

    with pytest.raises(AnswerGenerationError, match="Frozen Evidence"):
        await generator.generate(
            question="有什么要求？",
            snapshot=None,
            stage_policy=LLMStagePolicy(False, True),
        )

    assert client.calls == []


@pytest.mark.asyncio
async def test_answer_generator_uses_frozen_evidence_and_reasoning_off() -> None:
    snapshot = make_snapshot()
    client = FakeModelClient(
        [
            ModelResponse(
                content=(
                    '{"kind":"knowledge_answer","answer":"应按本标准执行。",'
                    '"citations":["E1"]}'
                )
            )
        ]
    )
    generator = AnswerGenerator(model_client=client)

    answer = await generator.generate(
        question="重庆市滑坡监测有什么要求？",
        snapshot=snapshot,
        stage_policy=LLMStagePolicy(True, True),
    )

    assert answer.kind == "knowledge_answer"
    assert answer.citations == ("E1",)
    assert client.calls[0].stage == "answer_generation"
    assert client.calls[0].request_reasoning is False
    assert "重庆市滑坡监测应按本标准执行" in client.calls[0].messages[-1]["content"]


@pytest.mark.asyncio
async def test_empty_content_retries_once_without_reading_reasoning_content() -> None:
    snapshot = make_snapshot()
    client = FakeModelClient(
        [
            ModelResponse(
                content="",
                reasoning_content=(
                    '{"kind":"knowledge_answer","answer":"不应读取这里",'
                    '"citations":["E1"]}'
                ),
            ),
            ModelResponse(
                content=(
                    '{"kind":"knowledge_answer","answer":"干净重试成功",'
                    '"citations":["E1"]}'
                )
            ),
        ]
    )
    generator = AnswerGenerator(model_client=client)

    answer = await generator.generate(
        question="要求？",
        snapshot=snapshot,
        stage_policy=LLMStagePolicy(True, True),
    )

    assert answer.answer == "干净重试成功"
    assert len(client.calls) == 2
    assert all(call.request_reasoning is False for call in client.calls)


@pytest.mark.asyncio
async def test_invalid_structured_output_retries_only_once() -> None:
    snapshot = make_snapshot()
    client = FakeModelClient(
        [
            ModelResponse(content="not-json"),
            ModelResponse(content="still-not-json"),
        ]
    )
    generator = AnswerGenerator(model_client=client)

    with pytest.raises(AnswerGenerationError, match="structured output"):
        await generator.generate(
            question="要求？",
            snapshot=snapshot,
            stage_policy=LLMStagePolicy(True, True),
        )

    assert len(client.calls) == 2
