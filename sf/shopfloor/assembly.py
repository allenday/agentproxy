"""
AssemblyStation
===============

First-class station for integrating parallel results.
Merges child worktree branches into parent via git merge --no-ff.

Design principle: Andon signaling — MergeResult with conflict details
is immediate problem signaling, not retroactive detection.
"""

import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..telemetry import get_telemetry
from ..workstation.workstation import Workstation


class IntegrationStatus(str, Enum):
    """Outcome of an assembly integration."""
    SUCCESS = "success"
    CONFLICT = "conflict"
    FAILED = "failed"


@dataclass
class IntegrationResult:
    """Result of merging a child fixture into the parent."""
    status: IntegrationStatus
    merged_files: List[str] = field(default_factory=list)
    conflicted_files: List[str] = field(default_factory=list)
    conflict_diff: str = ""
    message: str = ""


class AssemblyStation:
    """Integrates sub-assemblies from parallel workstations.

    Poka-yoke: isolation via git worktrees makes corruption impossible.
    Assembly is the only point where work from parallel workstations converges.
    """

    def integrate(
        self,
        parent: Workstation,
        child: Workstation,
    ) -> IntegrationResult:
        """Merge child's fixture branch into parent via git merge --no-ff.

        Args:
            parent: The parent workstation (merge target).
            child: The child workstation (merge source).

        Returns:
            IntegrationResult with merge outcome.
        """
        telemetry = get_telemetry()
        start_time = time.time()

        # Start OTEL span
        span = None
        if telemetry.enabled and telemetry.tracer:
            span = telemetry.tracer.start_span("assembly.integration")

        integration_result = self._do_integrate(parent, child)

        # Record OTEL metrics
        duration = time.time() - start_time
        if telemetry.enabled and hasattr(telemetry, "assembly_integrations"):
            telemetry.assembly_integrations.add(1, {
                "status": integration_result.status.value,
            })
        if span:
            span.set_attribute("assembly.status", integration_result.status.value)
            span.set_attribute("assembly.duration_s", duration)
            span.set_attribute("assembly.merged_files", len(integration_result.merged_files))
            span.set_attribute("assembly.conflicted_files", len(integration_result.conflicted_files))
            span.end()

        return integration_result

    def _do_integrate(
        self,
        parent: Workstation,
        child: Workstation,
    ) -> IntegrationResult:
        """Internal merge logic."""
        # Get child branch name
        child_fixture = child.fixture
        if not hasattr(child_fixture, "branch"):
            return IntegrationResult(
                status=IntegrationStatus.FAILED,
                message="Child fixture has no branch (not a git fixture).",
            )

        child_branch = child_fixture.branch

        try:
            # Merge child branch into parent
            result = subprocess.run(
                ["git", "merge", "--no-ff", child_branch, "-m",
                 f"assembly: merge {child_branch}"],
                cwd=parent.path,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                # Successful merge — get list of changed files
                changed = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
                    cwd=parent.path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                merged_files = [f for f in changed.stdout.strip().split("\n") if f]
                return IntegrationResult(
                    status=IntegrationStatus.SUCCESS,
                    merged_files=merged_files,
                    message=f"Merged {child_branch} ({len(merged_files)} files).",
                )
            else:
                # Merge conflict
                conflict_diff = result.stdout + result.stderr

                # Get list of conflicted files
                status_result = subprocess.run(
                    ["git", "diff", "--name-only", "--diff-filter=U"],
                    cwd=parent.path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                conflicted = [f for f in status_result.stdout.strip().split("\n") if f]

                # Abort the merge to leave parent clean
                subprocess.run(
                    ["git", "merge", "--abort"],
                    cwd=parent.path,
                    capture_output=True,
                    timeout=10,
                )

                return IntegrationResult(
                    status=IntegrationStatus.CONFLICT,
                    conflicted_files=conflicted,
                    conflict_diff=conflict_diff,
                    message=f"Conflict merging {child_branch}: {', '.join(conflicted)}",
                )

        except subprocess.TimeoutExpired:
            # Abort on timeout
            subprocess.run(
                ["git", "merge", "--abort"],
                cwd=parent.path,
                capture_output=True,
                timeout=10,
            )
            return IntegrationResult(
                status=IntegrationStatus.FAILED,
                message=f"Merge timed out for {child_branch}.",
            )
        except Exception as e:
            return IntegrationResult(
                status=IntegrationStatus.FAILED,
                message=f"Merge failed: {e}",
            )

    def integrate_remote(
        self,
        parent: Workstation,
        remote_branch: str,
        remote_name: str = "origin",
    ) -> IntegrationResult:
        """Integrate a remote worker's branch via git fetch + merge --no-ff.

        Used for Celery distributed dispatch (Phase 4): the worker pushes
        to a remote branch, and the supervisor fetches and merges it.

        Args:
            parent: The parent workstation (merge target).
            remote_branch: Branch name on the remote (e.g., "wo-0").
            remote_name: Git remote name (default "origin").

        Returns:
            IntegrationResult with merge outcome.
        """
        telemetry = get_telemetry()
        start_time = time.time()

        span = None
        if telemetry.enabled and telemetry.tracer:
            span = telemetry.tracer.start_span(
                "assembly.remote_integration",
                attributes={
                    "assembly.remote_branch": remote_branch,
                    "assembly.remote_name": remote_name,
                },
            )

        try:
            # Fetch the remote branch
            fetch_result = subprocess.run(
                ["git", "fetch", remote_name, remote_branch],
                cwd=parent.path,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if fetch_result.returncode != 0:
                result = IntegrationResult(
                    status=IntegrationStatus.FAILED,
                    message=f"git fetch failed: {fetch_result.stderr[:200]}",
                )
            else:
                # Merge the fetched branch
                merge_ref = f"{remote_name}/{remote_branch}"
                result = self._do_merge(parent, merge_ref)

            # Record OTEL
            duration = time.time() - start_time
            if telemetry.enabled and hasattr(telemetry, "assembly_remote_integrations"):
                telemetry.assembly_remote_integrations.add(1, {
                    "status": result.status.value,
                })
            if span:
                span.set_attribute("assembly.status", result.status.value)
                span.set_attribute("assembly.duration_s", duration)
                span.end()

            return result

        except Exception as e:
            if span:
                span.end()
            return IntegrationResult(
                status=IntegrationStatus.FAILED,
                message=f"Remote integration failed: {e}",
            )

    def _do_merge(
        self,
        parent: Workstation,
        merge_ref: str,
    ) -> IntegrationResult:
        """Perform git merge --no-ff of a ref into parent.

        Args:
            parent: Target workstation.
            merge_ref: Git ref to merge (branch name or remote/branch).

        Returns:
            IntegrationResult.
        """
        try:
            result = subprocess.run(
                ["git", "merge", "--no-ff", merge_ref, "-m",
                 f"assembly: merge {merge_ref}"],
                cwd=parent.path,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                changed = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
                    cwd=parent.path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                merged_files = [f for f in changed.stdout.strip().split("\n") if f]
                return IntegrationResult(
                    status=IntegrationStatus.SUCCESS,
                    merged_files=merged_files,
                    message=f"Merged {merge_ref} ({len(merged_files)} files).",
                )
            else:
                conflict_diff = result.stdout + result.stderr
                status_result = subprocess.run(
                    ["git", "diff", "--name-only", "--diff-filter=U"],
                    cwd=parent.path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                conflicted = [f for f in status_result.stdout.strip().split("\n") if f]
                subprocess.run(
                    ["git", "merge", "--abort"],
                    cwd=parent.path,
                    capture_output=True,
                    timeout=10,
                )
                return IntegrationResult(
                    status=IntegrationStatus.CONFLICT,
                    conflicted_files=conflicted,
                    conflict_diff=conflict_diff,
                    message=f"Conflict merging {merge_ref}: {', '.join(conflicted)}",
                )

        except subprocess.TimeoutExpired:
            subprocess.run(
                ["git", "merge", "--abort"],
                cwd=parent.path,
                capture_output=True,
                timeout=10,
            )
            return IntegrationResult(
                status=IntegrationStatus.FAILED,
                message=f"Merge timed out for {merge_ref}.",
            )
        except Exception as e:
            return IntegrationResult(
                status=IntegrationStatus.FAILED,
                message=f"Merge failed: {e}",
            )

    def resolve_conflict(
        self,
        result: IntegrationResult,
        shopfloor: Any,  # Forward ref to avoid circular import
        context: Dict[str, Any],
    ) -> None:
        """Dispatch a conflict resolution work order (Andon response).

        Creates a new WorkOrder to resolve the merge conflict,
        feeding it back into the ShopFloor production loop.

        Args:
            result: The IntegrationResult with conflict details.
            shopfloor: ShopFloor instance to dispatch the resolution work order.
            context: Additional context (e.g., original work orders involved).
        """
        from .models import WorkOrder

        # Create a resolution work order
        resolution_prompt = (
            f"Resolve merge conflict in files: {', '.join(result.conflicted_files)}.\n"
            f"Conflict details:\n{result.conflict_diff[:2000]}\n"
            f"Context: {context.get('summary', 'parallel work order integration')}"
        )

        resolution_wo = WorkOrder(
            index=-1,  # Will be assigned by shopfloor
            prompt=resolution_prompt,
            source="quality_gate",
            source_ref="merge_conflict",
        )

        # The shopfloor will handle dispatching this
        if hasattr(shopfloor, "_dispatch_resolution"):
            shopfloor._dispatch_resolution(resolution_wo, result)
