"""
Orchestrator module - Coordinates planning, delegation, and supervision.

Core Philosophy:
- 90% planning/research, 10% guiding implementation
- Thorough Q&A until complete clarity before execution
- Orchestrator delegates to supervised subagents
- Independent verification (not self-verify)

Components:
- Planner: Interactive planning sessions with thorough Q&A
- Delegator: Task breakdown and context building for subagents
- Supervisor: Monitor subagent progress and handle checkpoints
- Verifier: Independent verification gate for task completion
- ContextBuilder: Build and budget context for subagents
"""

from .planner import Planner, PlanningSession
from .delegator import TaskDelegator
from .supervisor import Supervisor
from .verifier import Verifier
from .context_builder import ContextBuilder

__all__ = [
	"Planner",
	"PlanningSession",
	"TaskDelegator",
	"Supervisor",
	"Verifier",
	"ContextBuilder",
]
