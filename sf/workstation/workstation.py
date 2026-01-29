"""
Workstation
===========

The isolated execution environment. HAS-A Fixture, HAS hooks, HAS-A SOP.
Manages lifecycle: commission -> produce -> checkpoint -> decommission.

During commission, if an SOP is attached, it materializes as:
  - CLAUDE.md written to workstation path (Claude reads natively)
  - .claude/settings.json hooks written for enforcement
"""

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional

from .capabilities import WorkstationCapabilities
from .fixtures.base import Fixture


class WorkstationState(str, Enum):
    """Lifecycle states for a Workstation."""
    IDLE = "idle"
    COMMISSIONING = "commissioning"
    READY = "ready"
    PRODUCING = "producing"
    CHECKPOINT = "checkpoint"
    DECOMMISSIONING = "decommissioning"
    DECOMMISSIONED = "decommissioned"


class WorkstationHook(ABC):
    """Pre/post hooks for workstation lifecycle extensibility.

    Connects to the Plugin Architecture (Phase 2). Hooks on workstation
    lifecycle are the factory equivalent of PA lifecycle plugins.
    """

    @abstractmethod
    def pre_commission(self, station: "Workstation") -> None:
        """Called before workstation setup. E.g., validate environment."""

    @abstractmethod
    def post_production(self, station: "Workstation") -> None:
        """Called after work completes. E.g., run linters, security scan."""

    @abstractmethod
    def on_checkpoint(self, station: "Workstation", commit_hash: str) -> None:
        """Called after checkpoint. E.g., update Jira, notify Slack."""


class Workstation:
    """Isolated execution environment for a work order.

    A Workstation HAS-A Fixture (VCS strategy), HAS lifecycle hooks,
    and optionally HAS-A SOP (Standard Operating Procedure).

    During commission, the SOP is materialized:
      - CLAUDE.md written to workstation path
      - .claude/settings.json hooks written for enforcement
      - Pre-conditions checked
    """

    def __init__(
        self,
        fixture: Fixture,
        capabilities: Any = None,
        hooks: Optional[List[WorkstationHook]] = None,
        sop: Any = None,
    ):
        # Accept both typed WorkstationCapabilities and legacy Dict[str, Any]
        if isinstance(capabilities, WorkstationCapabilities):
            self.capabilities: WorkstationCapabilities = capabilities
        elif isinstance(capabilities, dict) and capabilities:
            self.capabilities = WorkstationCapabilities(**capabilities)
        else:
            self.capabilities = WorkstationCapabilities()

        self.fixture = fixture
        self.hooks: List[WorkstationHook] = hooks or []
        self.sop = sop  # Optional[SOP] - lazy import to avoid circular
        self.state: WorkstationState = WorkstationState.IDLE

    def commission(self) -> str:
        """Set up the workstation. Returns working directory path.

        Calls pre_commission hooks, then fixture.setup().
        If an SOP is attached, materializes CLAUDE.md + hooks.
        Records setup_time metric for SMED tracking.
        """
        start_time = time.time()
        self.state = WorkstationState.COMMISSIONING
        for hook in self.hooks:
            hook.pre_commission(self)
        path = self.fixture.setup()

        # Materialize SOP if attached
        if self.sop is not None:
            self.sop.materialize(path)
            # Run pre-conditions
            errors = self.sop.run_pre_conditions(path)
            if errors:
                import logging
                logger = logging.getLogger(__name__)
                for err in errors:
                    logger.warning("SOP pre-condition: %s", err)

        self.state = WorkstationState.READY

        # Record OTEL workstation setup time
        try:
            from ..telemetry import get_telemetry
            telemetry = get_telemetry()
            if telemetry.enabled and telemetry.tracer:
                duration = time.time() - start_time
                if hasattr(telemetry, "workstation_setup_time"):
                    fixture_type = self.fixture.serialize().get("type", "unknown")
                    telemetry.workstation_setup_time.record(
                        duration, {"fixture_type": fixture_type},
                    )
        except Exception:
            pass  # Telemetry should never break workstation lifecycle

        return path

    def decommission(self) -> None:
        """Tear down the workstation.

        Calls post_production hooks, then fixture.teardown().
        SOP artifacts (CLAUDE.md, .claude/) are cleaned up automatically
        when the fixture removes the working directory.
        """
        self.state = WorkstationState.DECOMMISSIONING
        for hook in self.hooks:
            hook.post_production(self)
        self.fixture.teardown()
        self.state = WorkstationState.DECOMMISSIONED

    def checkpoint(self, message: str) -> Optional[str]:
        """Snapshot workpiece state for integration.

        Returns commit hash or None.
        """
        prev_state = self.state
        self.state = WorkstationState.CHECKPOINT
        result = self.fixture.checkpoint(message)
        if result and self.hooks:
            for hook in self.hooks:
                hook.on_checkpoint(self, result)
        self.state = prev_state if prev_state != WorkstationState.CHECKPOINT else WorkstationState.PRODUCING
        return result

    def spawn(self, name: str) -> "Workstation":
        """Commission a parallel workstation (fork/worktree).

        Creates a child workstation with the same capabilities, hooks,
        and SOP but an isolated fixture.

        Args:
            name: Identifier for the child (used in branch names, etc.)

        Returns:
            New Workstation instance with a forked fixture.
        """
        child_fixture = self.fixture.fork(name)
        return Workstation(
            fixture=child_fixture,
            capabilities=self.capabilities.model_copy(),
            hooks=list(self.hooks),
            sop=self.sop,
        )

    @property
    def path(self) -> str:
        """Absolute path to the working directory."""
        return self.fixture.path

    def serialize(self) -> Dict[str, Any]:
        """Serialize workstation state for Celery transport."""
        data: Dict[str, Any] = {
            "fixture": self.fixture.serialize(),
            "capabilities": self.capabilities.model_dump(),
            "state": self.state.value,
        }
        if self.sop is not None:
            data["sop"] = self.sop.model_dump()
        return data

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "Workstation":
        """Reconstruct a Workstation from serialized data."""
        from .sop import SOP

        fixture = Fixture.deserialize(data["fixture"])
        caps = WorkstationCapabilities(**data.get("capabilities", {}))

        sop = None
        if "sop" in data and data["sop"] is not None:
            sop = SOP(**data["sop"])

        return Workstation(
            fixture=fixture,
            capabilities=caps,
            sop=sop,
        )
