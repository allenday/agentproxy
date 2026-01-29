"""
SupervisorPA (Phase 6)
======================

Hierarchical delegation: a Supervisor PA decomposes large projects
into sub-projects, assigns them to Worker PAs (each with their own
ShopFloor), monitors progress via telemetry.

Architecture:
    SupervisorPA (Gemini reasoning)
        +-- ShopFloor (supervisor level)
            +-- WO: "Build auth module" -> WorkerPA-1
            |   +-- Sub-ShopFloor -> Sub-BOM
            +-- WO: "Build dashboard" -> WorkerPA-2
            |   +-- Sub-ShopFloor -> Sub-BOM
            +-- Assembly: merge WorkerPA-1 + WorkerPA-2

Key insight: PA already has the right state machine. PA.state, PA.reset(),
PA.run_task() compose naturally into a hierarchy.
"""

import logging
import time
from typing import Any, Dict, Generator, List, Optional

from .models import EventType, OutputEvent
from .telemetry import get_telemetry
from .workstation.workstation import Workstation
from .shopfloor.models import WorkOrder, WorkOrderResult, WorkOrderStatus

logger = logging.getLogger(__name__)


class SupervisorPA:
    """Supervisor PA that manages Worker PAs for hierarchical delegation.

    The Supervisor PA:
    1. Receives complex work orders from the ShopFloor
    2. Decomposes them into sub-work-orders
    3. Spawns Worker PAs to execute each sub-work-order
    4. Monitors progress and intervenes if stuck
    5. Assembles results back into the parent workstation

    Each Worker PA is a full PA instance with its own Workstation, SOP,
    and optionally its own ShopFloor for further sub-decomposition.
    """

    def __init__(self, pa: Any, max_workers: int = 4, max_depth: int = 3):
        """Initialize Supervisor.

        Args:
            pa: The root PA instance (the supervisor's own PA).
            max_workers: Maximum concurrent Worker PAs.
            max_depth: Maximum delegation depth (prevents infinite recursion).
        """
        self.pa = pa
        self.max_workers = max_workers
        self.max_depth = max_depth
        self._active_workers: Dict[int, Any] = {}  # wo_index -> worker state
        self._depth = 0

    def delegate_to_worker(
        self,
        wo: WorkOrder,
        station: Workstation,
        prior_context: List[str],
        max_iterations: int,
    ) -> Generator[OutputEvent, None, Optional[WorkOrderResult]]:
        """Delegate a work order to a Worker PA.

        The Worker PA gets its own workstation (spawned from the parent),
        inherits the SOP, and executes the work order independently.

        Args:
            wo: Work order to delegate.
            station: Parent workstation to spawn from.
            prior_context: Context summaries from prior work.
            max_iterations: Max iterations for the worker.

        Yields:
            OutputEvent stream.

        Returns:
            WorkOrderResult from the worker.
        """
        telemetry = get_telemetry()

        if self._depth >= self.max_depth:
            yield OutputEvent(
                event_type=EventType.ERROR,
                content=f"[Supervisor] Max delegation depth ({self.max_depth}) reached",
                source="supervisor",
            )
            return WorkOrderResult(
                status="failed",
                summary=f"Max delegation depth {self.max_depth} reached",
                work_order_index=wo.index,
            )

        if len(self._active_workers) >= self.max_workers:
            yield OutputEvent(
                event_type=EventType.ERROR,
                content=f"[Supervisor] Max workers ({self.max_workers}) reached",
                source="supervisor",
            )
            return WorkOrderResult(
                status="failed",
                summary=f"Max workers {self.max_workers} reached",
                work_order_index=wo.index,
            )

        # Track active worker
        self._active_workers[wo.index] = {
            "status": "starting",
            "started_at": time.time(),
        }

        if telemetry.enabled and hasattr(telemetry, "supervisor_workers_active"):
            telemetry.supervisor_workers_active.add(1)
            telemetry.supervisor_delegation_depth.record(self._depth + 1)

        # Spawn a child workstation for the worker
        worker_station = station.spawn(f"worker-{wo.index}")
        worker_station.commission()

        yield OutputEvent(
            event_type=EventType.TEXT,
            content=f"[Supervisor] Worker PA for WO-{wo.index} commissioned at {worker_station.path}",
            source="supervisor",
        )

        try:
            # Execute using PA's _stream_claude on the worker's workstation
            self._active_workers[wo.index]["status"] = "producing"
            start_time = time.time()

            prompt = wo.prompt
            if prior_context:
                context_str = "\n".join(f"- {s}" for s in prior_context[-5:])
                prompt = f"Context from prior work:\n{context_str}\n\nCurrent task:\n{prompt}"

            events: List[Dict] = []
            for event in self.pa._stream_claude(prompt, working_dir=worker_station.path):
                yield event
                events.append({
                    "type": event.event_type.value,
                    "content": event.content[:500],
                })

            # Checkpoint
            commit = worker_station.checkpoint(f"Worker-WO-{wo.index}: {wo.prompt[:50]}")
            duration = time.time() - start_time

            yield OutputEvent(
                event_type=EventType.TEXT,
                content=f"[Supervisor] Worker WO-{wo.index} completed in {duration:.1f}s",
                source="supervisor",
            )

            # Record cost
            if telemetry.enabled and hasattr(telemetry, "supervisor_total_cost"):
                # Cost would be calculated from token usage
                pass

            result = WorkOrderResult(
                status="completed",
                events=events,
                summary=f"Worker WO-{wo.index} completed in {duration:.1f}s",
                duration=duration,
                work_order_index=wo.index,
            )

        except Exception as e:
            duration = time.time() - start_time
            yield OutputEvent(
                event_type=EventType.ERROR,
                content=f"[Supervisor] Worker WO-{wo.index} failed: {e}",
                source="supervisor",
            )

            if telemetry.enabled and hasattr(telemetry, "supervisor_intervention"):
                telemetry.supervisor_intervention.add(1, {"reason": "worker_failure"})

            result = WorkOrderResult(
                status="failed",
                events=[],
                summary=f"Worker WO-{wo.index} failed: {e}",
                duration=duration,
                work_order_index=wo.index,
            )

        finally:
            # Clean up
            worker_station.decommission()
            self._active_workers.pop(wo.index, None)
            if telemetry.enabled and hasattr(telemetry, "supervisor_workers_active"):
                telemetry.supervisor_workers_active.add(-1)

        return result

    @property
    def active_worker_count(self) -> int:
        """Number of active Worker PAs."""
        return len(self._active_workers)

    @property
    def depth(self) -> int:
        """Current delegation depth."""
        return self._depth
