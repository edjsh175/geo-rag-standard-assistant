"""Optional Claim ↔ Frozen Evidence grounding reviewer."""

from __future__ import annotations

from dataclasses import dataclass
import json
from time import monotonic
from uuid import uuid4

from app.services.agent.answer_generator import GeneratedAnswer
from app.services.agent.contracts import FrozenEvidenceSnapshot
from app.services.agent.model_client import ModelRequest, StageModelClient
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.structured_candidate import (
    StructuredCandidateProtocolError,
    execute_structured_candidate,
)


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    unit_id: str
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
        model_name: str | None = None,
    ) -> ReviewResult:
        evidence_text = "\n\n".join(
            f"[{item.citation_id}] {item.text}" for item in snapshot.items
        )
        messages = (
                {
                    "role": "system",
                    "content": (
                        "Validate every answer unit against the provided Frozen Evidence. "
                        "Return JSON with verdict and findings. Each finding must reference "
                        "exactly one unit_id and every answer unit must appear exactly once. Do not plan "
                        "retrieval and do not add external knowledge."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{question}\n\nAnswer Units:\n"
                        f"{json.dumps([{'unit_id': unit.unit_id, 'text': unit.text, 'citations': list(unit.citations)} for unit in answer.units], ensure_ascii=False)}\n\n"
                        f"Frozen Evidence:\n{evidence_text}"
                    ),
                },
        )
        execution = stage_policy.for_stage("reviewer")
        call_id = str(uuid4())
        deadline_at = monotonic() + execution.timeout_seconds

        async def generate_candidate(attempt):
            remaining = deadline_at - monotonic()
            if remaining <= 0:
                raise TimeoutError("reviewer model call deadline exceeded")
            request = ModelRequest(
                stage="reviewer",
                messages=messages,
                request_reasoning=(
                    stage_policy.for_stage("reviewer").request_reasoning
                    if attempt.request_reasoning is None
                    else attempt.request_reasoning
                ),
                model_name=model_name,
                temperature=(0.2 if attempt.temperature is None else attempt.temperature),
                call_id=call_id,
                attempt=attempt.protocol_attempt,
                timeout_seconds=remaining,
            )
            return (await self.model_client.complete(request)).content

        expected_unit_ids = tuple(unit.unit_id for unit in answer.units)
        try:
            return await execute_structured_candidate(
                generate=generate_candidate,
                validate=lambda content: self._parse(
                    content,
                    snapshot=snapshot,
                    expected_unit_ids=expected_unit_ids,
                ),
            )
        except StructuredCandidateProtocolError as exc:
            raise ValueError("reviewer returned invalid structured output") from exc

    @staticmethod
    def _parse(
        content: str | None,
        *,
        snapshot: FrozenEvidenceSnapshot,
        expected_unit_ids: tuple[str, ...],
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
        seen_unit_ids: set[str] = set()
        for raw in raw_findings:
            if not isinstance(raw, dict):
                raise ValueError("reviewer returned invalid structured output")
            unit_id = raw.get("unit_id")
            status = raw.get("status")
            citations = raw.get("citations", [])
            if (
                not isinstance(unit_id, str)
                or unit_id not in expected_unit_ids
                or unit_id in seen_unit_ids
                or not isinstance(status, str)
                or not isinstance(citations, list)
                or not all(isinstance(value, str) for value in citations)
                or any(value not in allowed for value in citations)
            ):
                raise ValueError("reviewer returned invalid structured output")
            normalized_status = status.strip().upper()
            if normalized_status not in {"SUPPORTED", "UNSUPPORTED", "OVERSTATED"}:
                raise ValueError("reviewer returned invalid finding status")
            if normalized_status == "SUPPORTED" and not citations:
                raise ValueError("supported review finding requires citations")
            seen_unit_ids.add(unit_id)
            findings.append(
                ReviewFinding(
                    unit_id=unit_id,
                    status=normalized_status,
                    citations=tuple(citations),
                )
            )
        if seen_unit_ids != set(expected_unit_ids):
            raise ValueError("reviewer must cover every answer unit exactly once")
        finding_statuses = {finding.status for finding in findings}
        if normalized_verdict == "SUPPORTED" and finding_statuses != {"SUPPORTED"}:
            raise ValueError("supported verdict conflicts with review findings")
        if normalized_verdict == "UNSUPPORTED" and "UNSUPPORTED" not in finding_statuses:
            raise ValueError("unsupported verdict conflicts with review findings")
        if normalized_verdict == "OVERSTATED" and "OVERSTATED" not in finding_statuses:
            raise ValueError("overstated verdict conflicts with review findings")
        return ReviewResult(verdict=normalized_verdict, findings=tuple(findings))
