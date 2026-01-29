"""
Workstation Package
===================

Isolated execution environments for work orders.
A Workstation HAS-A Fixture (VCS strategy), lifecycle hooks, and an SOP.
"""

from .workstation import Workstation, WorkstationState, WorkstationHook
from .capabilities import WorkstationCapabilities
from .sop import SOP, ClaudeHook, SOP_V0, SOP_HOTFIX, SOP_REFACTOR, SOP_DOCUMENTATION, get_sop, register_sop, SOP_REGISTRY
from .fixtures import (
    Fixture, LocalDirFixture, GitRepoFixture, GitWorktreeFixture, GitCloneFixture,
)
from .quality_gate import QualityGate, VerificationGate, HumanApprovalGate, InspectionResult

__all__ = [
    "Workstation",
    "WorkstationState",
    "WorkstationHook",
    "WorkstationCapabilities",
    "SOP",
    "ClaudeHook",
    "SOP_V0",
    "SOP_HOTFIX",
    "SOP_REFACTOR",
    "SOP_DOCUMENTATION",
    "SOP_REGISTRY",
    "get_sop",
    "register_sop",
    "Fixture",
    "LocalDirFixture",
    "GitRepoFixture",
    "GitWorktreeFixture",
    "GitCloneFixture",
    "QualityGate",
    "VerificationGate",
    "HumanApprovalGate",
    "InspectionResult",
    "create_workstation",
]


def create_workstation(
    working_dir: str,
    *,
    context_type: str = "auto",
    repo_url: str = "",
    capabilities: dict = None,
    hooks: list = None,
    sop_name: str = None,
) -> Workstation:
    """Factory function to create a Workstation with the appropriate Fixture.

    Args:
        working_dir: Path to the working directory.
        context_type: One of "auto", "local", "git". Default "auto" detects.
        repo_url: Git remote URL (for clone-based fixtures).
        capabilities: Dict of workstation capabilities.
        hooks: List of WorkstationHook instances.
        sop_name: Name of the SOP to attach (from registry).

    Returns:
        Configured Workstation instance (not yet commissioned).
    """
    import os
    import subprocess

    capabilities = capabilities or {}
    hooks = hooks or []

    if context_type == "auto":
        # Detect: is working_dir inside a git repo?
        if os.path.isdir(os.path.join(working_dir, ".git")):
            context_type = "git"
        else:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--git-dir"],
                    cwd=working_dir,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                context_type = "git" if result.returncode == 0 else "local"
            except (subprocess.SubprocessError, FileNotFoundError):
                context_type = "local"

    if context_type == "clone" and repo_url:
        fixture = GitCloneFixture(
            repo_url=repo_url,
            clone_path=working_dir,
        )
    elif context_type == "git":
        fixture = GitRepoFixture(path=working_dir)
    else:
        fixture = LocalDirFixture(path=working_dir)

    # Resolve SOP
    sop = get_sop(sop_name) if sop_name else None

    return Workstation(
        fixture=fixture,
        capabilities=capabilities,
        hooks=hooks,
        sop=sop,
    )
