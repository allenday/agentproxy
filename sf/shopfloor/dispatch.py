"""
Dispatch Strategy
=================

Strategy pattern for work order dispatch. ShopFloor selects a dispatch
strategy based on configuration and work order requirements.

Strategies:
- DirectClaudeDispatch: Execute via PA._stream_claude() (current default)
- CeleryDispatch: Execute via Celery distributed task queue
- WorkerPADispatch: Execute via a spawned Worker PA with its own ShopFloor

The dispatch strategy decouples "what to execute" from "how to execute",
enabling hierarchical delegation (Phase 6).
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, List, Optional

from ..models import OutputEvent
from ..workstation.workstation import Workstation
from .models import WorkOrder, WorkOrderResult

logger = logging.getLogger(__name__)


class DispatchStrategy(ABC):
    """Abstract base for work order dispatch strategies.

    A DispatchStrategy defines how a single work order is executed.
    The ShopFloor calls strategy.dispatch() instead of directly
    invoking Claude or Celery.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy identifier."""
        ...

    @abstractmethod
    def dispatch(
        self,
        wo: WorkOrder,
        station: Workstation,
        prior_context: List[str],
        max_iterations: int,
        **kwargs: Any,
    ) -> Generator[OutputEvent, None, Optional[WorkOrderResult]]:
        """Execute a work order and yield output events.

        Args:
            wo: The work order to execute.
            station: The workstation to execute on.
            prior_context: Summaries from prior work orders.
            max_iterations: Maximum iterations.
            **kwargs: Strategy-specific arguments.

        Yields:
            OutputEvent stream.

        Returns:
            WorkOrderResult or None on failure.
        """
        ...


class DirectClaudeDispatch(DispatchStrategy):
    """Execute work orders via PA._stream_claude().

    This is the default strategy: the ShopFloor directly invokes
    Claude subprocess on the workstation's working directory.
    """

    def __init__(self, pa: Any):
        self.pa = pa

    @property
    def name(self) -> str:
        return "direct_claude"

    def dispatch(
        self,
        wo: WorkOrder,
        station: Workstation,
        prior_context: List[str],
        max_iterations: int,
        **kwargs: Any,
    ) -> Generator[OutputEvent, None, Optional[WorkOrderResult]]:
        """Dispatch via Claude subprocess on station's working directory."""
        import time
        from datetime import datetime

        from .models import WorkOrderStatus

        wo.status = WorkOrderStatus.IN_PROGRESS
        start_time = time.time()

        prompt = wo.prompt
        if prior_context:
            context_str = "\n".join(f"- {s}" for s in prior_context[-5:])
            prompt = f"Context from prior work:\n{context_str}\n\nCurrent task:\n{prompt}"

        events: List[Dict] = []
        try:
            for event in self.pa._stream_claude(prompt, working_dir=station.path):
                yield event
                events.append({
                    "type": event.event_type.value,
                    "content": event.content[:500],
                })

            commit = station.checkpoint(f"WO-{wo.index}: {wo.prompt[:50]}")
            duration = time.time() - start_time
            wo.status = WorkOrderStatus.COMPLETED
            wo.completed_at = datetime.utcnow().isoformat()

            return WorkOrderResult(
                status="completed",
                events=events,
                summary=f"WO-{wo.index} completed in {duration:.1f}s",
                duration=duration,
                work_order_index=wo.index,
            )
        except Exception as e:
            duration = time.time() - start_time
            wo.status = WorkOrderStatus.FAILED
            return WorkOrderResult(
                status="failed",
                events=events,
                summary=f"WO-{wo.index} failed: {e}",
                duration=duration,
                work_order_index=wo.index,
            )


class CeleryDispatch(DispatchStrategy):
    """Execute work orders via Celery distributed task queue.

    Serializes WorkOrder + Workstation and submits to a Celery queue.
    The remote worker reconstructs the environment and runs Claude.
    """

    def __init__(self, queue: str = "default"):
        self.queue = queue

    @property
    def name(self) -> str:
        return "celery"

    def dispatch(
        self,
        wo: WorkOrder,
        station: Workstation,
        prior_context: List[str],
        max_iterations: int,
        **kwargs: Any,
    ) -> Generator[OutputEvent, None, Optional[WorkOrderResult]]:
        """Dispatch via Celery remote worker."""
        from ..models import EventType

        try:
            from .tasks import run_work_order
        except ImportError:
            yield OutputEvent(
                event_type=EventType.ERROR,
                content="[CeleryDispatch] Celery not available",
                source="dispatch",
            )
            return None

        target_queue = kwargs.get("target_queue", self.queue)

        yield OutputEvent(
            event_type=EventType.TEXT,
            content=f"[CeleryDispatch] Submitting WO-{wo.index} to queue '{target_queue}'",
            source="dispatch",
        )

        async_result = run_work_order.apply_async(
            args=[
                wo.serialize(),
                station.serialize(),
                prior_context[-5:],
            ],
            queue=target_queue,
        )

        try:
            result_data = async_result.get(timeout=600)
            return WorkOrderResult.deserialize(result_data)
        except Exception as e:
            yield OutputEvent(
                event_type=EventType.ERROR,
                content=f"[CeleryDispatch] WO-{wo.index} failed: {e}",
                source="dispatch",
            )
            return WorkOrderResult(
                status="failed",
                summary=f"Celery dispatch failed: {e}",
                work_order_index=wo.index,
            )


class WorkerPADispatch(DispatchStrategy):
    """Execute work orders via a spawned Worker PA with its own ShopFloor.

    Phase 6: enables hierarchical delegation. A Supervisor PA decomposes
    large work orders into sub-projects, assigns them to Worker PAs.

    The Worker PA gets its own Workstation, SOP, and optionally its own
    ShopFloor for sub-decomposition.
    """

    def __init__(self, supervisor: Any):
        """Initialize with reference to the Supervisor PA.

        Args:
            supervisor: SupervisorPA instance.
        """
        self.supervisor = supervisor

    @property
    def name(self) -> str:
        return "worker_pa"

    def dispatch(
        self,
        wo: WorkOrder,
        station: Workstation,
        prior_context: List[str],
        max_iterations: int,
        **kwargs: Any,
    ) -> Generator[OutputEvent, None, Optional[WorkOrderResult]]:
        """Dispatch via a Worker PA with its own ShopFloor.

        The Worker PA is a full PA instance that can decompose the
        work order into sub-work-orders and execute them independently.
        """
        from ..models import EventType

        yield OutputEvent(
            event_type=EventType.TEXT,
            content=f"[WorkerPA] Delegating WO-{wo.index} to Worker PA",
            source="dispatch",
        )

        try:
            # The supervisor spawns a worker for this WO
            result = yield from self.supervisor.delegate_to_worker(
                wo, station, prior_context, max_iterations,
            )
            return result
        except Exception as e:
            yield OutputEvent(
                event_type=EventType.ERROR,
                content=f"[WorkerPA] WO-{wo.index} delegation failed: {e}",
                source="dispatch",
            )
            return WorkOrderResult(
                status="failed",
                summary=f"Worker PA delegation failed: {e}",
                work_order_index=wo.index,
            )
