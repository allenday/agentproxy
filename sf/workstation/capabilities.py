"""
WorkstationCapabilities
=======================

Typed capability model for workstation routing eligibility.
Replaces the untyped Dict[str, Any] with a Pydantic schema
that the scheduler uses to match work orders to workstations.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class WorkstationCapabilities(BaseModel):
    """What this workstation can do. Defines routing eligibility.

    In manufacturing, capabilities define what a workstation can produce
    and what a worker is trained to do. The scheduler routes work orders
    to workstations whose capabilities satisfy the order's requirements.
    """

    # VCS / isolation
    fixture_type: str = "local"  # "local", "git_repo", "git_worktree", "git_clone"
    supports_parallel: bool = False  # Can spawn children (worktree/clone)

    # Installed tooling
    languages: List[str] = Field(default_factory=list)
    package_managers: List[str] = Field(default_factory=list)
    runtimes: Dict[str, str] = Field(default_factory=dict)
    tools: List[str] = Field(default_factory=list)

    # Resources
    gpu: bool = False
    memory_gb: float = 8.0
    disk_gb: float = 50.0
    network_access: bool = True

    # Agent (the worker is a Claude sub-agent)
    agent_model: str = "claude-sonnet-4-5"
    context_window: int = 200_000
    max_output_tokens: int = 16_000
    tool_permissions: List[str] = Field(
        default_factory=lambda: ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    )

    # SOP (attached during commission, materialized as CLAUDE.md + hooks)
    sop_name: Optional[str] = None

    def to_match_dict(self) -> Dict:
        """Convert to flat dict for match_capabilities() compatibility.

        match_capabilities() in routing.py does key-value matching.
        This bridges the typed model to the existing matching logic.
        """
        d = self.model_dump()
        # Flatten for matching: lists become sets for containment checks
        return d
