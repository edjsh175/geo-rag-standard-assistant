"""Grounded answer generation from immutable Frozen Evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json

from app.services.agent.contracts import FrozenEvidenceSnapshot
from app.services.agent.model_client import ModelRequest, StageModelClient
from app.services.agent.stage_policy import LLMStagePolicy


class AnswerGenerationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    kind: str
    answer: str
    citations: tuple[str, ...] = ()


class AnswerGenerator:
    def __init__(self, *, model_client: StageModelClient) -> None:
        self.model_client = model_client

    async def generate(
        self,
        *,
        question: str,
        snapshot: FrozenEvidenceSnapshot | None,
        stage_policy: LLMStagePolicy,
    ) -> GeneratedAnswer:
        if snapshot is None or not snapshot.items:
            raise AnswerGenerationError(
                "knowledge answers require a non-empty Frozen Evidence snapshot"
            )

        request = self._build_request(
            question=question,
            snapshot=snapshot,
            stage_policy=stage_policy,
        )
        first = await self.model_client.complete(request)
        parsed = self._try_parse(first.content, snapshot=snapshot)
        if parsed is not None:
            return parsed

        retry_request = ModelRequest(
            stage="answer_generation",
            messages=request.messages,
            request_reasoning=False,
        )
        second = await self.model_client.complete(retry_request)
        parsed = self._try_parse(second.content, snapshot=snapshot)
        if parsed is None:
            raise AnswerGenerationError(
                "answer generation failed to produce valid structured output"
            )
        return parsed

    def _build_request(
        self,
        *,
        question: str,
        snapshot: FrozenEvidenceSnapshot,
        stage_policy: LLMStagePolicy,
    ) -> ModelRequest:
        evidence_text = "\n\n".join(
            f"[{item.citation_id}] {item.title}\n{item.text}"
            for item in snapshot.items
        )
        messages = (
            {
                "role": "system",
                "content": (
                    "Generate only a grounded answer from the provided Frozen Evidence. "
                    "Return JSON with kind, answer, citations. Do not introduce external facts."
                ),
            },
            {
                "role": "user",
                "content": f"Question:\n{question}\n\nFrozen Evidence:\n{evidence_text}",
            },
        )
        return ModelRequest(
            stage="answer_generation",
            messages=messages,
            request_reasoning=stage_policy.for_stage(
                "answer_generation"
            ).request_reasoning,
        )

    @staticmethod
    def _try_parse(
        content: str | None,
        *,
        snapshot: FrozenEvidenceSnapshot,
    ) -> GeneratedAnswer | None:
        if not content or not content.strip():
            return None
        try:
            payload = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None

        kind = payload.get("kind")
        answer = payload.get("answer")
        citations = payload.get("citations", [])
        if kind != "knowledge_answer" or not isinstance(answer, str) or not answer.strip():
            return None
        if not isinstance(citations, list) or not all(
            isinstance(value, str) for value in citations
        ):
            return None

        allowed = {item.citation_id for item in snapshot.items}
        if not citations or any(citation not in allowed for citation in citations):
            return None
        return GeneratedAnswer(
            kind="knowledge_answer",
            answer=answer.strip(),
            citations=tuple(citations),
        )
