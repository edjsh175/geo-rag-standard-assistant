from __future__ import annotations

from datetime import datetime
import json

import pytest

from app.models.search_models import DocumentResult
from app.services.agent.answer_generator import (
    AnswerGenerationError,
    AnswerGenerator,
    AnswerUnit,
    GeneratedAnswer,
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


def test_answer_units_are_separate_paragraphs_without_changing_unit_or_citation_data() -> None:
    snapshot = make_snapshot()
    payload = json.dumps(
        {
            "kind": "knowledge_answer",
            "units": [
                {"unit_id": "u1", "text": "已确认适用。", "citations": ["E1"]},
                {"unit_id": "u2", "text": "适用范围仍有待核验项。", "citations": ["E1"]},
            ],
        },
        ensure_ascii=False,
    )

    answer = AnswerGenerator._parse(payload, snapshot=snapshot)

    assert answer.answer == "已确认适用。\n\n适用范围仍有待核验项。"
    assert [(unit.unit_id, unit.text, unit.citations) for unit in answer.units] == [
        ("u1", "已确认适用。", ("E1",)),
        ("u2", "适用范围仍有待核验项。", ("E1",)),
    ]
    assert answer.citations == ("E1",)


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
                    '{"kind":"knowledge_answer","units":['
                    '{"unit_id":"u1","text":"应按本标准执行。","citations":["E1"]}'
                    ']}'
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
    assert '"const": "knowledge_answer"' in client.calls[0].messages[0]["content"]
    assert '"enum": ["E1"]' in client.calls[0].messages[0]["content"]
    instructions = client.calls[0].messages[0]["content"]
    assert "unresolved_count" in instructions and "not the number confirmed applicable" in instructions
    assert "next_cursor" in instructions and "not whether results are paginated" in instructions
    assert "complete Markdown block" in instructions
    assert "plain user-facing language rather than dumping raw field names or JSON" in instructions


@pytest.mark.asyncio
async def test_answer_generator_passes_provider_native_response_schema() -> None:
    snapshot = make_snapshot()
    client = FakeModelClient(
        [
            ModelResponse(
                content=(
                    '{"kind":"knowledge_answer","units":['
                    '{"unit_id":"u1","text":"应按本标准执行。","citations":["E1"]}'
                    ']}'
                )
            )
        ]
    )
    generator = AnswerGenerator(model_client=client)

    await generator.generate(
        question="要求？",
        snapshot=snapshot,
        stage_policy=LLMStagePolicy(False, False),
    )

    assert client.calls[0].response_schema == generator._output_schema(snapshot)


def test_answer_unit_markdown_text_is_preserved_verbatim() -> None:
    snapshot = make_snapshot()
    markdown = "**结论**\n\n- 依据一\n- 依据二"
    payload = json.dumps(
        {
            "kind": "knowledge_answer",
            "units": [{"unit_id": "u1", "text": markdown, "citations": ["E1"]}],
        },
        ensure_ascii=False,
    )

    answer = AnswerGenerator._parse(payload, snapshot=snapshot)

    assert answer.units[0].text == markdown
    assert answer.answer == markdown


@pytest.mark.asyncio
async def test_answer_repair_passes_provider_native_response_schema() -> None:
    snapshot = make_snapshot()
    base_answer = GeneratedAnswer(
        kind="knowledge_answer",
        answer="原回答",
        citations=("E1",),
        units=(AnswerUnit(unit_id="u1", text="原回答", citations=("E1",)),),
    )
    client = FakeModelClient(
        [
            ModelResponse(
                content=(
                    '{"kind":"knowledge_answer","units":['
                    '{"unit_id":"u1","text":"修复回答","citations":["E1"]}'
                    ']}'
                )
            )
        ]
    )
    generator = AnswerGenerator(model_client=client)

    await generator.generate_repair(
        question="要求？",
        snapshot=snapshot,
        base_answer=base_answer,
        repair_scope={
            "contract_version": "answer_repair_scope_v1",
            "immutable_units": [],
            "editable_units": [
                {"unit_id": "u1", "allowed_evidence_ids": ["E1"]}
            ],
        },
        stage_policy=LLMStagePolicy(False, False),
    )

    assert client.calls[0].response_schema == generator._output_schema(snapshot)
    repair_prompt = client.calls[0].messages[0]["content"]
    assert "applies only to Editable Units" in repair_prompt
    assert "Immutable Units must remain byte-for-byte unchanged" in repair_prompt
    assert "Do not add an answer field" in repair_prompt


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
                    '{"kind":"knowledge_answer","units":['
                    '{"unit_id":"u1","text":"干净重试成功","citations":["E1"]}'
                    ']}'
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


@pytest.mark.asyncio
async def test_answer_units_have_stable_ids_and_clean_retry_uses_same_model() -> None:
    snapshot = make_snapshot()
    client = FakeModelClient(
        [
            ModelResponse(content='{"kind":"knowledge_answer","answer":"bad","citations":["E9"]}'),
            ModelResponse(
                content=(
                    '{"kind":"knowledge_answer","units":['
                    '{"unit_id":"u1","text":"应按本标准执行。","citations":["E1"]}'
                    ']}'
                )
            ),
        ]
    )
    generator = AnswerGenerator(model_client=client)

    answer = await generator.generate(
        question="要求？",
        snapshot=snapshot,
        stage_policy=LLMStagePolicy(True, True),
        model_name="stable-main",
    )

    assert answer.answer == "应按本标准执行。"
    assert answer.units[0].unit_id == "u1"
    assert answer.citations == ("E1",)
    assert len(client.calls) == 2
    assert [call.model_name for call in client.calls] == ["stable-main", "stable-main"]
    assert client.calls[1].request_reasoning is False


@pytest.mark.asyncio
async def test_answer_generator_rejects_map_action_side_effect_field() -> None:
    snapshot = make_snapshot()
    client = FakeModelClient(
        [
            ModelResponse(
                content=(
                    '{"kind":"knowledge_answer","units":['
                    '{"unit_id":"u1","text":"grounded","citations":["E1"]}'
                    '],"map_action":{"type":"locate_map","target":"map"}}'
                )
            ),
            ModelResponse(
                content=(
                    '{"kind":"knowledge_answer","units":['
                    '{"unit_id":"u1","text":"grounded","citations":["E1"]}'
                    '],"map_action":{"type":"locate_map","target":"map"}}'
                )
            ),
        ]
    )
    generator = AnswerGenerator(model_client=client)

    with pytest.raises(AnswerGenerationError, match="structured output"):
        await generator.generate(
            question="question",
            snapshot=snapshot,
            stage_policy=LLMStagePolicy(False, False),
        )

    assert len(client.calls) == 2
