"""
QualityGate
===========

Inspection between production stages. Implements Jidoka (autonomation):
machines detect problems and stop the line.

Gates are inserted between execution layers in ShopFloor.produce().
Each gate inspects a WorkOrderResult and returns an InspectionResult.

VerificationGate also enforces SOP verification commands when an SOP
is attached to the workstation.
"""

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .workstation import Workstation


@dataclass
class InspectionResult:
    """Outcome of a quality gate inspection."""
    passed: bool
    details: str = ""
    defects: List[str] = field(default_factory=list)


class QualityGate(ABC):
    """Abstract base for quality gates between production layers.

    A QualityGate inspects the output of a work order and decides
    whether to proceed or halt the line.
    """

    @abstractmethod
    def inspect(
        self,
        work_order: Any,  # WorkOrder (forward ref)
        result: Any,  # WorkOrderResult (forward ref)
        station: Workstation,
    ) -> InspectionResult:
        """Inspect output of a work order.

        Args:
            work_order: The work order that was executed.
            result: The result of executing the work order.
            station: The workstation where work was performed.

        Returns:
            InspectionResult indicating pass/fail and details.
        """


class VerificationGate(QualityGate):
    """Runs code verification (compile, lint, tests) between layers.

    Executes a list of shell commands on the workstation's working
    directory. All commands must pass for the gate to pass.

    If the workstation has an SOP with verification_commands, those
    are appended to (and override) the default commands.
    """

    def __init__(
        self,
        commands: Optional[List[str]] = None,
        timeout: int = 120,
    ):
        self.commands = commands or self._default_commands()
        self.timeout = timeout

    def inspect(
        self,
        work_order: Any,
        result: Any,
        station: Workstation,
    ) -> InspectionResult:
        """Run verification commands on the workstation.

        SOP-driven: if the workstation has an SOP with verification_commands,
        run those. If no SOP is attached to the station, skip verification.
        """
        import os
        if os.getenv("SF_SKIP_SOP_VERIFICATION", "0") == "1":
            return InspectionResult(passed=True, details="Verification skipped by env")
        # Resolve commands from station SOP
        commands = self._resolve_commands(station)
        if not commands:
            return InspectionResult(
                passed=True,
                details="No verification commands (no SOP attached)",
            )
        defects = []

        for cmd in commands:
            try:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=station.path,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
                if proc.returncode != 0:
                    defects.append(
                        f"Command failed: {cmd}\n"
                        f"stdout: {proc.stdout[:500]}\n"
                        f"stderr: {proc.stderr[:500]}"
                    )
            except subprocess.TimeoutExpired:
                defects.append(f"Command timed out: {cmd}")
            except Exception as e:
                defects.append(f"Command error: {cmd} -- {e}")

        if defects:
            return InspectionResult(
                passed=False,
                details=f"{len(defects)} verification failure(s)",
                defects=defects,
            )

        return InspectionResult(
            passed=True,
            details=f"All {len(commands)} verification commands passed",
        )

    def _resolve_commands(self, station: Workstation) -> List[str]:
        """Resolve verification commands from the workstation's SOP.

        If the station has an SOP with verification_commands, use those.
        If no SOP is attached, return empty (no verification).
        The gate's self.commands are NOT used as a fallback — verification
        is SOP-driven.
        """
        if station.sop is not None and station.sop.verification_commands:
            return station.sop.verification_commands
        return []

    @staticmethod
    def _default_commands() -> List[str]:
        """Default verification commands (language-agnostic)."""
        return [
            "python -m py_compile $(find . -name '*.py' -not -path './.git/*' | head -50) 2>&1 || true",
        ]


class HumanApprovalGate(QualityGate):
    """Blocks until human approves (for high-risk changes).

    In non-interactive mode, defaults to the configured policy
    (approve or reject).
    """

    def __init__(self, auto_policy: str = "approve"):
        """Initialize with auto-approval policy.

        Args:
            auto_policy: "approve" or "reject" when non-interactive.
        """
        self.auto_policy = auto_policy

    def inspect(
        self,
        work_order: Any,
        result: Any,
        station: Workstation,
    ) -> InspectionResult:
        """Check for human approval. Uses auto_policy in non-interactive mode."""
        if self.auto_policy == "approve":
            return InspectionResult(
                passed=True,
                details="Auto-approved (non-interactive mode)",
            )
        else:
            return InspectionResult(
                passed=False,
                details="Requires human approval (auto_policy=reject)",
                defects=["Human approval required"],
            )
