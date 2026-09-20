"""Optional Claim ↔ Frozen Evidence grounding reviewer."""

from __future__ import annotations

from dataclasses import dataclass
import json

from app.services.agent.answer_generator import GeneratedAnswer
from app.services.agent.contracts import FrozenEvidenceSnapshot
from app.services.agent.model_client import ModelRequest, StageModelClient
from app.services.agent.stage_policy import LLMStagePolicy


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    claim: str
    status: str
    citations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewResult:
    verdict: str
    findings: tuple[ReviewFinding, ...]


class GroundingReviewer:
    def __init__(self, *, model_client: StageModelClient) -> None:
        self.model_client = model_client

    async def review(
        self,
        *,
        question: str,
        answer: GeneratedAnswer,
        snapshot: FrozenEvidenceSnapshot,
        stage_policy: LLMStagePolicy,
    ) -> ReviewResult:
        evidence_text = "\n\n".join(
            f"[{item.citation_id}] {item.text}" for item in snapshot.items
        )
        request = ModelRequest(
            stage="reviewer",
            messages=(
                {
                    "role": "system",
                    "content": (
                        "Validate only whether answer claims are supported by the provided "
                        "Frozen Evidence. Return JSON with verdict and findings. Do not plan "
                        "retrieval and do not add external knowledge."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{question}\n\nAnswer:\n{answer.answer}\n\n"
                        f"Answer Citations:\n{json.dumps(list(answer.citations), ensure_ascii=False)}\n\n"
                        f"Frozen Evidence:\n{evidence_text}"
                    ),
                },
            ),
            request_reasoning=stage_policy.for_stage("reviewer").request_reasoning,
        )
        response = await self.model_client.complete(request)
        return self._parse(response.content, snapshot=snapshot)

    @staticmethod
    def _parse(
        content: str | None,
        *,
        snapshot: FrozenEvidenceSnapshot,
    ) -> ReviewResult:
        if not content:
            raise ValueError("reviewer returned empty structured output")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("reviewer returned invalid structured output") from exc
        if not isinstance(payload, dict):
            raise ValueError("reviewer returned invalid structured output")

        verdict = payload.get("verdict")
        raw_findings = payload.get("findings")
        if not isinstance(verdict, str) or not isinstance(raw_findings, list):
            raise ValueError("reviewer returned invalid structured output")
        normalized_verdict = verdict.strip().upper()
        if normalized_verdict not in {"SUPPORTED", "UNSUPPORTED", "OVERSTATED"}:
            raise ValueError("reviewer returned invalid verdict")

        allowed = {item.citation_id for item in snapshot.items}
        findings: list[ReviewFinding] = []
        for raw in raw_findings:
            if not isinstance(raw, dict):
                raise ValueError("reviewer returned invalid structured output")
            claim = raw.get("claim")
            status = raw.get("status")
            citations = raw.get("citations", [])
            if (
                not isinstance(claim, str)
                or not isinstance(status, str)
                or not isinstance(citations, list)
                or not all(isinstance(value, str) for value in citations)
                or any(value not in allowed for value in citations)
            ):
                raise ValueError("reviewer returned invalid structured output")
            normalized_status = status.strip().upper()
            if normalized_status not in {"SUPPORTED", "UNSUPPORTED", "OVERSTATED"}:
                raise ValueError("reviewer returned invalid finding status")
            findings.append(
                ReviewFinding(
                    claim=claim,
                    status=normalized_status,
                    citations=tuple(citations),
                )
            )
        return ReviewResult(verdict=normalized_verdict, findings=tuple(findings))
