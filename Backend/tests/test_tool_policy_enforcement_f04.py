from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.services.agent.evidence import EvidenceLedger
from app.services.agent.tool_policy import (
    ToolConfirmationRequired,
    ToolExecutionContext,
    ToolPermissionDenied,
    ToolPolicy,
    ToolPolicyViolation,
    ToolSideEffectDenied,
)
from app.services.agent.tool_runtime import (
    ToolCall,
    ToolExecutionError,
    ToolRuntime,
)
from app.services.agent.tools import ToolRegistry, ToolSpec
from app.services.rag.contracts import RetrievalPort, RetrievalQuery, RetrievalResult


class DummyInput(BaseModel):
    query: str = "default"


class DummyRetrievalPort(RetrievalPort):
    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        raise NotImplementedError

    async def fetch_chunks(self, chunk_ids: list[str]) -> list:
        return []


def test_f04_side_effect_policy_denies_execution_when_disallowed() -> None:
    policy = ToolPolicy()
    spec = ToolSpec(
        name="mutate_state",
        description="A mutating tool",
        input_model=DummyInput,
        side_effect=True,
    )

    # Disallow side effects
    ctx_disallowed = ToolExecutionContext(allow_side_effects=False)
    with pytest.raises(ToolSideEffectDenied, match="TOOL_SIDE_EFFECT_DENIED: 'mutate_state' has side-effects"):
        policy.authorize(spec=spec, tool_call_id="call-1", context=ctx_disallowed)

    # Allow side effects
    ctx_allowed = ToolExecutionContext(allow_side_effects=True)
    policy.authorize(spec=spec, tool_call_id="call-1", context=ctx_allowed)


def test_f04_permission_policy_denies_missing_permissions() -> None:
    policy = ToolPolicy()
    spec = ToolSpec(
        name="admin_tool",
        description="Requires admin permission",
        input_model=DummyInput,
        permission="admin:execute",
    )

    # Missing permission
    ctx_no_perm = ToolExecutionContext(permissions=frozenset({"user:read"}))
    with pytest.raises(ToolPermissionDenied, match="TOOL_PERMISSION_DENIED: 'admin_tool' requires permission 'admin:execute'"):
        policy.authorize(spec=spec, tool_call_id="call-1", context=ctx_no_perm)

    # Has permission
    ctx_has_perm = ToolExecutionContext(permissions=frozenset({"user:read", "admin:execute"}))
    policy.authorize(spec=spec, tool_call_id="call-1", context=ctx_has_perm)


def test_f04_confirmation_policy_requires_explicit_call_confirmation() -> None:
    policy = ToolPolicy()
    spec = ToolSpec(
        name="delete_data",
        description="Requires human confirmation",
        input_model=DummyInput,
        confirmation_required=True,
    )

    # Unconfirmed call id
    ctx_unconfirmed = ToolExecutionContext(confirmed_tool_call_ids=frozenset({"call-other"}))
    with pytest.raises(ToolConfirmationRequired, match="TOOL_CONFIRMATION_REQUIRED: 'delete_data' requires explicit confirmation"):
        policy.authorize(spec=spec, tool_call_id="call-target", context=ctx_unconfirmed)

    # Confirmed call id
    ctx_confirmed = ToolExecutionContext(confirmed_tool_call_ids=frozenset({"call-target"}))
    policy.authorize(spec=spec, tool_call_id="call-target", context=ctx_confirmed)


def test_f04_allowed_providers_gate_enforces_provider_boundaries() -> None:
    policy = ToolPolicy()
    spec_postgis = ToolSpec(
        name="postgis_tool",
        description="Spatial tool",
        input_model=DummyInput,
        provider="postgis",
    )

    # Provider not in allowed set
    ctx_restricted = ToolExecutionContext(allowed_providers=frozenset({"kb", "server"}))
    with pytest.raises(ToolPermissionDenied, match="TOOL_PROVIDER_DENIED: 'postgis_tool' provider 'postgis' is not permitted"):
        policy.authorize(spec=spec_postgis, tool_call_id="call-1", context=ctx_restricted)

    # Provider in allowed set
    ctx_allowed = ToolExecutionContext(allowed_providers=frozenset({"kb", "server", "postgis"}))
    policy.authorize(spec=spec_postgis, tool_call_id="call-1", context=ctx_allowed)


def test_f04_tool_runtime_enforces_policies_in_validate_call() -> None:
    spec = ToolSpec(
        name="dangerous_tool",
        description="Side effect tool requiring permission",
        input_model=DummyInput,
        side_effect=True,
        permission="danger:run",
    )
    registry = ToolRegistry((spec,))

    runtime = ToolRuntime(
        retrieval_port=DummyRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-test"),
        registry=registry,
        execution_context=ToolExecutionContext(
            allow_side_effects=False,
            permissions=frozenset({"danger:run"}),
        ),
    )

    call = ToolCall(tool_call_id="call-1", name="dangerous_tool", arguments={"query": "test"})

    with pytest.raises(ToolExecutionError, match="TOOL_SIDE_EFFECT_DENIED"):
        runtime.validate_call(call=call)
