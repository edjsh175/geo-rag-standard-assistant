"""Agent observability, execution trace, and diagnostics routes."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import AdminIdentity, UserIdentity
from app.core.security import require_authenticated_admin, require_authenticated_user
from app.services.agent.dependencies import get_agent_store
from app.services.agent.session_service import AgentSessionService
from app.services.agent.trace_service import AgentTraceService

router = APIRouter()
_store = get_agent_store()
_trace_service = AgentTraceService(_store)
_session_service = AgentSessionService(_store)


def get_agent_trace_service() -> AgentTraceService:
    return _trace_service


def get_agent_session_service() -> AgentSessionService:
    return _session_service


def _extract_principal(user: UserIdentity) -> str:
    if user.role == "visitor":
        if not user.visitor_id:
            raise HTTPException(status_code=400, detail="visitor_id is required")
        return f"visitor:{user.visitor_id}"
    return f"admin:{user.username}"


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(50, ge=1, le=100),
    current_user: UserIdentity = Depends(require_authenticated_user),
    session_service: AgentSessionService = Depends(get_agent_session_service),
) -> list[dict[str, Any]]:
    """List sessions owned by the authenticated principal."""
    principal = _extract_principal(current_user)
    return await session_service.list_sessions(principal_id=principal, limit=limit)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    current_user: UserIdentity = Depends(require_authenticated_user),
    session_service: AgentSessionService = Depends(get_agent_session_service),
) -> dict[str, Any]:
    """Create a new empty server-owned Agent session."""
    principal = _extract_principal(current_user)
    return await session_service.create_session(principal_id=principal)


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    current_user: UserIdentity = Depends(require_authenticated_user),
    session_service: AgentSessionService = Depends(get_agent_session_service),
) -> dict[str, Any]:
    """Retrieve full conversation history, messages, and turns for a session."""
    principal = _extract_principal(current_user)
    detail = await session_service.get_session_detail(
        principal_id=principal,
        session_id=session_id,
    )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )
    return detail


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    current_user: UserIdentity = Depends(require_authenticated_user),
    session_service: AgentSessionService = Depends(get_agent_session_service),
) -> dict[str, Any]:
    """Delete a session and clear associated pending executions."""
    principal = _extract_principal(current_user)
    success = await session_service.delete_session(
        principal_id=principal,
        session_id=session_id,
    )
    return {"session_id": session_id, "deleted": success}


@router.get("/sessions/{session_id}/turns/{turn_id}")
async def get_turn_trace(
    session_id: str,
    turn_id: str,
    principal_id: str | None = Query(None, description="Optional principal_id override; defaults to current admin"),
    current_admin: AdminIdentity = Depends(require_authenticated_admin),
    trace_service: AgentTraceService = Depends(get_agent_trace_service),
) -> dict[str, Any]:
    """Retrieve structured execution trace, ordered events, model calls, and snapshot refs for a turn."""
    effective_principal = principal_id or f"admin:{current_admin.username}"
    trace = await trace_service.get_turn_trace(
        principal_id=effective_principal,
        session_id=session_id,
        turn_id=turn_id,
    )
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Turn trace not found for session_id='{session_id}', turn_id='{turn_id}'",
        )
    return trace


@router.get("/traces/{trace_id}")
async def get_trace_by_id(
    trace_id: str,
    current_admin: AdminIdentity = Depends(require_authenticated_admin),
    trace_service: AgentTraceService = Depends(get_agent_trace_service),
) -> dict[str, Any]:
    """Retrieve turn execution trace by its unique trace_id."""
    effective_principal = f"admin:{current_admin.username}"
    trace = await trace_service.get_trace_by_id(
        principal_id=effective_principal,
        trace_id=trace_id,
    )
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution trace not found for trace_id='{trace_id}'",
        )
    return trace
