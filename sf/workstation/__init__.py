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
from .frontmatter import parse_frontmatter, validate_frontmatter, expand_templates, FrontmatterError
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
    "create_workstation_from_frontmatter",
]


def create_workstation(
    working_dir: str,
    *,
    context_type: str,
    repo_url: str = "",
    parent_path: str = "",
    worktree_path: str = "",
    branch: str = "",
    session_id: str = "",
    capabilities: dict = None,
    hooks: list = None,
    sop_name: str = None,
    telemetry_env: dict = None,
    llm_config: dict = None,
) -> Workstation:
    import os
    import subprocess
    import uuid
    """Factory function to create a Workstation with the specified Fixture.

    Args:
        working_dir: Path to the working directory (or worktree path when using git_worktree).
        context_type: One of {"local", "git_repo", "git_worktree", "git_clone"} (auto-detect removed).
        repo_url: Git remote URL (required for git_clone).
        parent_path: Parent repo path (required for git_worktree if working_dir is not inside the parent).
        worktree_path: Explicit worktree path (optional if working_dir is already the worktree path).
        branch: Branch name for git_worktree (required).
        capabilities: Dict of workstation capabilities.
        hooks: List of WorkstationHook instances.
        sop_name: Name of the SOP to attach (from registry).

    Returns:
        Configured Workstation instance (not yet commissioned).
    """
    import uuid
    capabilities = capabilities or {}
    hooks = hooks or []

    if context_type == "git_clone":
        if not repo_url:
            raise ValueError("repo_url is required when context_type='git_clone'")
        fixture = GitCloneFixture(repo_url=repo_url, clone_path=working_dir)
    elif context_type == "git_repo":
        fixture = GitRepoFixture(path=working_dir)
    elif context_type == "git_worktree":
        from .fixtures.git_worktree import GitWorktreeFixture
        wt_path = worktree_path or working_dir
        # Try to infer branch from existing worktree; if absent, derive from folder name or session_id.
        if not branch:
            try:
                branch = (
                    subprocess.check_output(
                        ["git", "-C", wt_path, "rev-parse", "--abbrev-ref", "HEAD"],
                        text=True,
                    )
                    .strip()
                )
            except Exception:
                pass
        if not branch:
            token = session_id or uuid.uuid4().hex[:6]
            folder = os.path.basename(wt_path.rstrip("/")) or "auto"
            branch = f"sf/{folder}-{token}"

        # Determine parent repo path
        parent = parent_path
        if not parent:
            try:
                parent = (
                    subprocess.check_output(
                        ["git", "-C", os.getcwd(), "rev-parse", "--show-toplevel"],
                        text=True,
                    )
                    .strip()
                )
            except Exception:
                parent = os.path.dirname(os.path.abspath(wt_path))

        # If worktree path was not provided, place it under parent/.worktrees with session-aware suffix.
        if not worktree_path:
            token = session_id or uuid.uuid4().hex[:6]
            inferred_name = f"{os.path.basename(branch).replace('/', '-')}-{token}"
            wt_path = os.path.join(parent, ".worktrees", inferred_name)

        fixture = GitWorktreeFixture(parent_path=parent, worktree_path=wt_path, branch=branch)
    elif context_type == "local":
        fixture = LocalDirFixture(path=working_dir)
    else:
        raise ValueError(f"Unsupported context_type: {context_type}")

    sop = get_sop(sop_name) if sop_name else None

    station = Workstation(
        fixture=fixture,
        capabilities=capabilities,
        hooks=hooks,
        sop=sop,
    )
    if telemetry_env:
        station.telemetry_env = telemetry_env
    if llm_config:
        station.llm_config = llm_config
    return station


def create_workstation_from_frontmatter(
    working_dir: str,
    frontmatter: dict,
    capabilities: dict = None,
    hooks: list = None,
) -> Workstation:
    """
    Build a workstation from expanded frontmatter (workstation block).
    """
    wm = frontmatter.get("workstation", {})
    vcs = wm.get("vcs", {})
    runtime = wm.get("runtime", {})
    telemetry = wm.get("telemetry", {})
    llm = wm.get("llm", {})
    tooling = wm.get("tooling", {})

    context_type = vcs.get("type")
    fixture_kwargs = {
        "working_dir": working_dir,
        "context_type": context_type,
        "repo_url": vcs.get("repo_url", ""),
        "parent_path": vcs.get("parent", ""),
        "worktree_path": vcs.get("worktree", ""),
        "branch": vcs.get("branch", ""),
        "capabilities": capabilities or {},
        "hooks": hooks or [],
        "sop_name": wm.get("sop", None),
    }
    station = create_workstation(
        **fixture_kwargs,
        telemetry_env=telemetry.get("env", {}),
        llm_config=llm,
    )

    # Attach runtime/tooling configs to station for later use
    station.runtime_config = runtime
    station.tooling_config = tooling
    return station
