from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping
from uuid import uuid4
from app.services.agent.events import AgentEvent
from app.services.agent.orchestration.browser_continuation import BrowserContinuationHandler
from app.services.agent.orchestration.session_loader import SessionLoader
from app.services.agent.session import AgentSession
from app.services.agent.tool_runtime import ToolObservation

@dataclass(frozen=True, slots=True)
class PreparedTurn:
    session: AgentSession
    question: str
    turn_id: str
    trace_id: str
    request_context: Mapping[str, Any]
    reviewer_enabled: bool
    thinking: bool
    retrieval_constraints: Any
    max_steps: int
    max_elapsed_seconds: float
    initial_steps: int
    main_model_name: str | None
    observations: tuple[ToolObservation, ...]

class TurnLifecycleCoordinator:
    """Prepare one authoritative turn; no planning/tool/publication semantics."""
    def __init__(self, session_store: Any) -> None:
        self.session_store=session_store
        self.session_loader=SessionLoader(session_store)
        self.browser_continuation=BrowserContinuationHandler(session_store)

    async def prepare(self, *, request: Any, append_turn_event: Callable[[AgentEvent], Awaitable[None]], append_session_event: Callable[[AgentEvent], Awaitable[None]], persist_evidence: Callable[[AgentSession], Awaitable[None]], resolve_main_model: Callable[[bool], str | None]) -> PreparedTurn:
        question=str(request.question).strip()
        if not question: raise ValueError("question must not be empty")
        loaded=await self.session_loader.load(principal_id=request.principal_id, session_id=request.session_id)
        session,pending=loaded.session,loaded.pending_execution
        if request.continuation_token is not None:
            resumed=await self.browser_continuation.resume(session=session, principal_id=request.principal_id, session_id=request.session_id, pending=pending, continuation_token=request.continuation_token, receipt=request.browser_tool_receipt)
            await persist_evidence(session); persisted=await append_turn_event(resumed.completion_event); session.events.append(persisted or resumed.completion_event)
            return PreparedTurn(session,resumed.question,resumed.turn_id,resumed.trace_id,resumed.request_context,resumed.reviewer_enabled,resumed.thinking,resumed.retrieval_constraints,resumed.max_steps,resumed.max_elapsed_seconds,resumed.initial_steps,resumed.main_model_name,resumed.observations)
        if request.browser_tool_receipt is not None: raise ValueError("browser_tool_receipt requires continuation_token")
        cancelled=await self.browser_continuation.supersede_pending(session=session, principal_id=request.principal_id, session_id=request.session_id, pending=pending)
        if cancelled is not None:
            persisted=await append_turn_event(cancelled); session.events.append(persisted or cancelled)
        if not session.events and request.legacy_history:
            for i,m in enumerate(request.legacy_history,1):
                role,content=m.get("role"),m.get("content")
                if role in {"user","assistant"} and isinstance(content,str) and content.strip():
                    event=AgentEvent(event_type="user_message" if role=="user" else "assistant_message", session_id=session.session_id, turn_id=f"legacy-{i}", trace_id="legacy-seed", payload={"text":content.strip()})
                    persisted=await append_session_event(event); session.events.append(persisted or event)
        turn_id=(await self.session_store.allocate_turn_id(request.principal_id,request.session_id)) if hasattr(self.session_store,"allocate_turn_id") else session.new_turn_id()
        trace_id=str(uuid4()); ctx=request.request_context; payload={"text":question}
        if isinstance(ctx,Mapping):
            ui=ctx.get("user_ui_selections")
            if isinstance(ui,Mapping) and ui: payload["user_ui_selections"]=dict(ui)
        event=AgentEvent(event_type="user_message",session_id=session.session_id,turn_id=turn_id,trace_id=trace_id,payload=payload)
        persisted=await append_turn_event(event); session.events.append(persisted or event)
        return PreparedTurn(session,question,turn_id,trace_id,ctx,request.reviewer_enabled,request.thinking,request.retrieval_constraints,request.max_steps,request.max_elapsed_seconds,0,resolve_main_model(bool(request.thinking)),())

__all__=["PreparedTurn","TurnLifecycleCoordinator"]
