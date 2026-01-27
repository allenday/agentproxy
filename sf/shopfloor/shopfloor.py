"""
ShopFloor
=========

The orchestration container. Replaces Coordinator.

Manufacturing-inspired agent orchestration:
- Poka-yoke: isolation via git worktrees makes corruption impossible
- SMED: git worktree add is near-instant changeover
- Jidoka: QualityGate detects problems and halts the line
- Kaizen: closed-loop feedback from telemetry → new work orders
- Andon: IntegrationResult with conflict details is immediate signaling
"""

import time
from typing import Any, Dict, Generator, List, Optional

from ..models import EventType, OutputEvent
from ..workstation.workstation import Workstation
from .assembly import AssemblyStation, IntegrationResult, IntegrationStatus
from .models import WorkOrder, WorkOrderResult, WorkOrderStatus
from .routing import build_layers, parse_work_orders


class ShopFloor:
    """Orchestration container. Replaces Coordinator.

    Manages the production lifecycle:
    1. Bill of Materials: decompose task into work orders
    2. Routing: topological sort into execution layers
    3. Execute layers (sequential or parallel via spawn)
    4. Assembly: merge parallel results
    5. Quality gates between layers
    """

    def __init__(self, pa: Any, queue: str = "default"):
        """Initialize ShopFloor.

        Args:
            pa: PA instance (forward reference to avoid circular import).
            queue: Celery queue name for dispatching.
        """
        self.pa = pa
        self.queue = queue
        self.assembly = AssemblyStation()
        self.quality_gates: List[Any] = []  # List[QualityGate]

    def produce(
        self,
        task: str,
        breakdown_text: str,
        max_iterations: int = 100,
    ) -> Generator[OutputEvent, None, None]:
        """Main production method. Replaces run_task_multi_worker.

        Args:
            task: The original task description.
            breakdown_text: Pre-generated task breakdown from Gemini.
            max_iterations: Max iterations per work order.

        Yields:
            OutputEvent stream.
        """
        # 1. Bill of Materials: parse breakdown into work orders
        bom = parse_work_orders(breakdown_text)
        if not bom:
            yield self._emit(
                "[ShopFloor] No work orders parsed from breakdown. "
                "Falling back to single work order.",
            )
            bom = [WorkOrder(index=0, prompt=task)]

        yield self._emit(
            f"[ShopFloor] Bill of Materials: {len(bom)} work orders",
        )
        for wo in bom:
            deps = f" (depends: {wo.depends_on})" if wo.depends_on else ""
            yield self._emit(f"  WO-{wo.index}: {wo.prompt[:80]}{deps}")

        # 2. Routing: topological sort into execution layers
        layers = build_layers(bom)
        yield self._emit(
            f"[ShopFloor] Routing: {len(layers)} execution layers",
        )
        for i, layer in enumerate(layers):
            indices = [wo.index for wo in layer]
            yield self._emit(f"  Layer {i+1}: WO-{indices}")

        # 3. Execute layers
        yield from self._execute_layers(layers, max_iterations)

    def _execute_layers(
        self,
        layers: List[List[WorkOrder]],
        max_iterations: int,
    ) -> Generator[OutputEvent, None, None]:
        """Execute layers: single orders direct, parallel orders via spawn.

        For each layer:
        - Single work order: dispatch on parent workstation
        - Multiple work orders: spawn child workstations, dispatch, assemble
        - Run quality gates between layers
        """
        parent_station = self.pa._workstation
        completed_results: List[WorkOrderResult] = []
        context_summaries: List[str] = []

        for layer_idx, layer in enumerate(layers):
            yield self._emit(
                f"\n[ShopFloor] === Layer {layer_idx + 1}/{len(layers)} "
                f"({len(layer)} work order{'s' if len(layer) > 1 else ''}) ===",
            )

            if len(layer) == 1:
                # Sequential — dispatch on parent workstation
                wo = layer[0]
                wo.status = WorkOrderStatus.DISPATCHED
                yield self._emit(f"[ShopFloor] Dispatching WO-{wo.index} (sequential)")

                result = yield from self._dispatch_single(
                    wo, parent_station, context_summaries, max_iterations,
                )
                if result:
                    completed_results.append(result)
                    context_summaries.append(result.summary)
            else:
                # Parallel — spawn child workstations
                yield self._emit(
                    f"[ShopFloor] Spawning {len(layer)} parallel workstations",
                )

                # Checkpoint parent before spawning
                parent_station.checkpoint(f"pre-spawn layer {layer_idx + 1}")

                children: List[Workstation] = []
                for wo in layer:
                    child = parent_station.spawn(f"wo-{wo.index}")
                    child.commission()
                    children.append(child)
                    wo.status = WorkOrderStatus.DISPATCHED

                # Dispatch to children (in current process for now)
                layer_results: List[WorkOrderResult] = []
                for wo, child in zip(layer, children):
                    yield self._emit(
                        f"[ShopFloor] Dispatching WO-{wo.index} to worktree",
                    )
                    result = yield from self._dispatch_single(
                        wo, child, context_summaries, max_iterations,
                    )
                    if result:
                        layer_results.append(result)

                # Assembly: merge children back
                for wo, child, result in zip(layer, children, layer_results):
                    yield self._emit(
                        f"[ShopFloor] Assembling WO-{wo.index} into parent",
                    )
                    integration = self.assembly.integrate(parent_station, child)

                    if integration.status == IntegrationStatus.SUCCESS:
                        yield self._emit(
                            f"[ShopFloor] Merged WO-{wo.index}: "
                            f"{len(integration.merged_files)} files",
                        )
                    elif integration.status == IntegrationStatus.CONFLICT:
                        yield self._emit(
                            f"[ShopFloor] CONFLICT merging WO-{wo.index}: "
                            f"{', '.join(integration.conflicted_files)}",
                            event_type=EventType.ERROR,
                        )
                        # Andon: resolve conflict
                        self.assembly.resolve_conflict(
                            integration, self,
                            {"summary": f"Layer {layer_idx + 1} parallel merge"},
                        )
                    else:
                        yield self._emit(
                            f"[ShopFloor] FAILED merging WO-{wo.index}: "
                            f"{integration.message}",
                            event_type=EventType.ERROR,
                        )

                    child.decommission()

                completed_results.extend(layer_results)
                for r in layer_results:
                    context_summaries.append(r.summary)

            # Quality gate between layers
            for gate in self.quality_gates:
                for wo_result in completed_results[-len(layer):]:
                    inspection = gate.inspect(
                        layer[0], wo_result, parent_station,
                    )
                    if not inspection.passed:
                        yield self._emit(
                            f"[QualityGate] FAILED: {inspection.details}",
                            event_type=EventType.ERROR,
                        )

        yield self._emit(
            f"\n[ShopFloor] Production complete: "
            f"{len(completed_results)} work orders executed",
        )

    def _dispatch_single(
        self,
        wo: WorkOrder,
        station: Workstation,
        prior_context: List[str],
        max_iterations: int,
    ) -> Generator[OutputEvent, None, Optional[WorkOrderResult]]:
        """Dispatch a single work order to a workstation.

        Uses the PA's single-worker loop on the workstation's working directory.

        Args:
            wo: The work order to execute.
            station: The workstation to execute on.
            prior_context: Summaries from prior work orders.
            max_iterations: Max iterations for this work order.

        Yields:
            OutputEvent stream.

        Returns:
            WorkOrderResult or None on failure.
        """
        wo.status = WorkOrderStatus.IN_PROGRESS
        start_time = time.time()

        # Build enriched prompt with context
        prompt = wo.prompt
        if prior_context:
            context_str = "\n".join(
                f"- {s}" for s in prior_context[-5:]  # Last 5 summaries
            )
            prompt = (
                f"Context from prior work:\n{context_str}\n\n"
                f"Current task:\n{prompt}"
            )

        # Execute using Claude subprocess on the station's working directory
        events: List[Dict] = []
        files_changed: List[str] = []
        summary = ""

        try:
            yield self._emit(
                f"[WO-{wo.index}] Starting: {wo.prompt[:80]}",
            )

            # Stream Claude on the workstation
            for event in self.pa._stream_claude(prompt, working_dir=station.path):
                yield event
                events.append({
                    "type": event.event_type.value,
                    "content": event.content[:500],
                    "source": event.source,
                })

            # Checkpoint after work
            commit = station.checkpoint(f"WO-{wo.index}: {wo.prompt[:50]}")
            if commit:
                yield self._emit(f"[WO-{wo.index}] Checkpoint: {commit[:8]}")

            duration = time.time() - start_time
            wo.status = WorkOrderStatus.COMPLETED
            summary = f"WO-{wo.index} completed in {duration:.1f}s"

            yield self._emit(f"[WO-{wo.index}] {summary}")

            return WorkOrderResult(
                status="completed",
                events=events,
                files_changed=files_changed,
                summary=summary,
                duration=duration,
                work_order_index=wo.index,
            )

        except Exception as e:
            duration = time.time() - start_time
            wo.status = WorkOrderStatus.FAILED
            yield self._emit(
                f"[WO-{wo.index}] FAILED: {e}",
                event_type=EventType.ERROR,
            )
            return WorkOrderResult(
                status="failed",
                events=events,
                files_changed=[],
                summary=f"WO-{wo.index} failed: {e}",
                duration=duration,
                work_order_index=wo.index,
            )

    def _dispatch_resolution(
        self,
        wo: WorkOrder,
        result: IntegrationResult,
    ) -> None:
        """Handle a conflict resolution work order. Placeholder for future."""
        pass

    def _emit(
        self,
        content: str,
        event_type: EventType = EventType.TEXT,
    ) -> OutputEvent:
        """Create an OutputEvent."""
        return OutputEvent(
            event_type=event_type,
            content=content,
            source="shopfloor",
        )
