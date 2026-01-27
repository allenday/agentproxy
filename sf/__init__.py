"""
SF (Software Factory)
===============================================

Manufacturing-inspired agent orchestration for coding agents (Claude Code, etc.).

Usage:
    from sf import PA

    pa = PA(working_dir=".", user_mission="Build a REST API")
    for event in pa.run_task("Create user endpoints"):
        print(event)
"""

from .models import OutputEvent, EventType, ControllerState
from .pa import PA, create_pa, list_sessions
from .pa_memory import PAMemory, BestPractices, SessionContext, InteractionHistory
from .process_manager import ClaudeProcessManager
from .display import RealtimeDisplay

__all__ = [
    # Primary API
    "PA",
    "create_pa",
    "list_sessions",
    # Memory system
    "PAMemory",
    "BestPractices",
    "SessionContext",
    "InteractionHistory",
    # Core components
    "ClaudeProcessManager", 
    "RealtimeDisplay",
    "OutputEvent",
    "EventType",
    "ControllerState",
]

__version__ = "0.2.0"
