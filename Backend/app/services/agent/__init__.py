"""Agent application core.

The package is intentionally independent from database and transport details.
"""

from app.services.agent.answer_generator import GeneratedAnswer
from app.services.agent.contracts import EvidenceItem, FrozenEvidenceSnapshot
from app.services.agent.controller import MainController
from app.services.agent.evidence import EvidenceLedger
from app.services.agent.reviewer import GroundingReviewer
from app.services.agent.runtime import AgentRunRequest, AgentRunResult, AgentRuntime
from app.services.agent.session import InMemoryAgentSessionStore
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.tool_runtime import ToolCall, ToolObservation, ToolRuntime

__all__ = [
    "AgentRunRequest",
    "AgentRunResult",
    "AgentRuntime",
    "GeneratedAnswer",
    "GroundingReviewer",
    "EvidenceItem",
    "EvidenceLedger",
    "FrozenEvidenceSnapshot",
    "InMemoryAgentSessionStore",
    "LLMStagePolicy",
    "MainController",
    "ToolCall",
    "ToolObservation",
    "ToolRuntime",
]
