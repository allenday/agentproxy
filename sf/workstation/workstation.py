"""
Workstation
===========

The isolated execution environment. HAS-A Fixture, HAS hooks.
Manages lifecycle: commission → produce → checkpoint → decommission.
"""

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional

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

    A Workstation HAS-A Fixture (VCS strategy) and lifecycle hooks.
    Separates lifecycle/hooks from VCS mechanics — hooks are portable
    across fixture types.
    """

    def __init__(
        self,
        fixture: Fixture,
        capabilities: Dict[str, Any] = None,
        hooks: List[WorkstationHook] = None,
    ):
        self.fixture = fixture
        self.capabilities: Dict[str, Any] = capabilities or {}
        self.hooks: List[WorkstationHook] = hooks or []
        self.state: WorkstationState = WorkstationState.IDLE

    def commission(self) -> str:
        """Set up the workstation. Returns working directory path.

        Calls pre_commission hooks, then fixture.setup().
        Records setup_time metric for SMED tracking.
        """
        start_time = time.time()
        self.state = WorkstationState.COMMISSIONING
        for hook in self.hooks:
            hook.pre_commission(self)
        path = self.fixture.setup()
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

        Creates a child workstation with the same capabilities and hooks
        but an isolated fixture.

        Args:
            name: Identifier for the child (used in branch names, etc.)

        Returns:
            New Workstation instance with a forked fixture.
        """
        child_fixture = self.fixture.fork(name)
        return Workstation(
            fixture=child_fixture,
            capabilities=dict(self.capabilities),
            hooks=list(self.hooks),
        )

    @property
    def path(self) -> str:
        """Absolute path to the working directory."""
        return self.fixture.path

    def serialize(self) -> Dict[str, Any]:
        """Serialize workstation state for Celery transport."""
        return {
            "fixture": self.fixture.serialize(),
            "capabilities": self.capabilities,
            "state": self.state.value,
            # Hooks are not serialized (they're code, not data)
        }

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "Workstation":
        """Reconstruct a Workstation from serialized data."""
        fixture = Fixture.deserialize(data["fixture"])
        return Workstation(
            fixture=fixture,
            capabilities=data.get("capabilities", {}),
        )
