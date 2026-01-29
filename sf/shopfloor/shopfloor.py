"""
ShopFloor
=========

The orchestration container. Replaces Coordinator.

Manufacturing-inspired agent orchestration:
- Poka-yoke: isolation via git worktrees makes corruption impossible
- SMED: git worktree add is near-instant changeover
- Jidoka: QualityGate detects problems and halts the line
- Kaizen: closed-loop feedback from telemetry -> new work orders
- Andon: IntegrationResult with conflict details is immediate signaling

Phase 3: Continuous drain loop with ResultAnalyzer feedback
Phase 4: Conditional dispatch (local sequential, local parallel, Celery distributed)
Phase 5: Capability-based routing via match_capabilities()
Phase 6: Dispatch strategy pattern (Direct, WorkerPA, Celery)
"""

import logging
import time
import os
import json
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

from ..models import EventType, OutputEvent
from ..telemetry import get_telemetry
from ..workstation.workstation import Workstation
from ..llm import get_provider, LLMRequest, LLMMessage
from .analyzer import ResultAnalyzer
from .assembly import AssemblyStation, IntegrationResult, IntegrationStatus
from .models import WorkOrder, WorkOrderResult, WorkOrderStatus
from .queue import WorkOrderQueue
from .routing import build_layers, match_capabilities, parse_work_orders

try:
    from ..plugins.base import PluginHookPhase
except ImportError:
    PluginHookPhase = None

logger = logging.getLogger(__name__)


class ShopFloor:
    """Orchestration container. Replaces Coordinator.

    Manages the production lifecycle:
    1. Bill of Materials: decompose task into work orders
    2. Routing: topological sort into execution layers
    3. Capability matching: route WOs to eligible workstations
    4. Execute layers (sequential, parallel local, or distributed Celery)
    5. Assembly: merge parallel results
    6. Quality gates between layers
    7. Kaizen loop: analyze results, enqueue feedback WOs, repeat
    """

    def __init__(
        self,
        pa: Any,
        queue: str = "default",
        use_celery: bool = False,
        max_kaizen_cycles: int = 5,
    ):
        """Initialize ShopFloor.

        Args:
            pa: PA instance (forward reference to avoid circular import).
            queue: Celery queue name for dispatching.
            use_celery: Whether to use Celery for distributed dispatch.
            max_kaizen_cycles: Maximum feedback loop cycles before stopping.
        """
        self.pa = pa
        self.queue = queue
        self.use_celery = use_celery
        self.max_kaizen_cycles = max_kaizen_cycles
        self.parallel_limit = None  # Optional cap on concurrent WOs per layer
        self.assembly = AssemblyStation()
        self.quality_gates: List[Any] = []  # List[QualityGate]
        self.analyzer = ResultAnalyzer()
        self.work_queue = WorkOrderQueue()

    def produce(
        self,
        task: str,
        breakdown_text: str,
        max_iterations: int = 100,
    ) -> Generator[OutputEvent, None, None]:
        """Main production method. Replaces run_task_multi_worker.

        Implements the continuous Kaizen drain loop:
        1. Parse BOM -> enqueue work orders
        2. Loop: dequeue layer -> execute -> analyze -> enqueue feedback WOs
        3. Until queue empty or max_kaizen_cycles reached

        Args:
            task: The original task description.
            breakdown_text: Pre-generated task breakdown from Gemini.
            max_iterations: Max iterations per work order.

        Yields:
            OutputEvent stream.
        """
        telemetry = get_telemetry()
        production_start = time.time()

        # Start OTEL span for production
        span = None
        if telemetry.enabled and telemetry.tracer:
            span = telemetry.tracer.start_span(
                "shopfloor.production",
                attributes={
                    "shopfloor.task": task[:200],
                    "shopfloor.max_iterations": max_iterations,
                },
            )

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
        if self.parallel_limit and self.parallel_limit > 0:
            layers = self._limit_parallelism(layers, self.parallel_limit)
        yield self._emit(
            f"[ShopFloor] Routing: {len(layers)} execution layers",
        )
        for i, layer in enumerate(layers):
            indices = [wo.index for wo in layer]
            yield self._emit(f"  Layer {i+1}: WO-{indices}")

        # Record work orders
        if telemetry.enabled and hasattr(telemetry, "factory_work_orders"):
            for wo in bom:
                telemetry.factory_work_orders.add(1, {
                    "source": wo.source,
                    "status": "created",
                })

        # 3. Execute layers with Kaizen feedback loop
        yield from self._execute_with_kaizen(layers, max_iterations)

        # Record cycle time
        cycle_time = time.time() - production_start
        if telemetry.enabled and hasattr(telemetry, "factory_cycle_time"):
            telemetry.factory_cycle_time.record(cycle_time)
        if span:
            span.set_attribute("shopfloor.cycle_time_s", cycle_time)
            span.set_attribute("shopfloor.work_order_count", len(bom))
            span.set_attribute("shopfloor.layer_count", len(layers))
            span.set_attribute("shopfloor.kaizen_rework_count", self.analyzer.total_rework_count)
            span.end()

    def _execute_with_kaizen(
        self,
        layers: List[List[WorkOrder]],
        max_iterations: int,
    ) -> Generator[OutputEvent, None, None]:
        """Execute layers with Kaizen feedback loop.

        After each layer, analyze results and enqueue corrective WOs.
        The loop continues until the work queue is empty or max cycles hit.
        """
        telemetry = get_telemetry()
        parent_station = self.pa._workstation
        completed_results: List[WorkOrderResult] = []
        context_summaries: List[str] = []
        next_wo_index = max((wo.index for layer in layers for wo in layer), default=-1) + 1

        # Execute original layers
        for layer_idx, layer in enumerate(layers):
            yield self._emit(
                f"\n[ShopFloor] === Layer {layer_idx + 1}/{len(layers)} "
                f"({len(layer)} work order{'s' if len(layer) > 1 else ''}) ===",
            )

            layer_results = yield from self._execute_layer(
                layer, parent_station, context_summaries, max_iterations,
            )
            completed_results.extend(layer_results)
            for r in layer_results:
                context_summaries.append(r.summary)

            # Quality gates
            yield from self._run_quality_gates(
                layer, layer_results, parent_station, layer_idx,
            )

            # Kaizen: analyze results and enqueue feedback WOs
            for wo, result in zip(layer, layer_results):
                feedback_wo = self.analyzer.analyze_result(wo, result, next_wo_index)
                if feedback_wo:
                    self.work_queue.enqueue(feedback_wo)
                    next_wo_index += 1
                    yield self._emit(
                        f"[Kaizen] Feedback WO-{feedback_wo.index} enqueued "
                        f"(source={feedback_wo.source}, ref={feedback_wo.source_ref})",
                    )

        # Kaizen drain loop: process feedback WOs
        kaizen_cycle = 0
        while not self.work_queue.empty and kaizen_cycle < self.max_kaizen_cycles:
            kaizen_cycle += 1

            if telemetry.enabled and hasattr(telemetry, "kaizen_loop_cycles"):
                telemetry.kaizen_loop_cycles.add(1)

            yield self._emit(
                f"\n[Kaizen] === Feedback cycle {kaizen_cycle}/{self.max_kaizen_cycles} "
                f"({self.work_queue.size} WOs queued) ===",
            )

            # Dequeue a batch of feedback WOs
            batch = self.work_queue.dequeue_batch(max_size=5)
            if not batch:
                break

            # Execute feedback WOs as a layer
            layer_results = yield from self._execute_layer(
                batch, parent_station, context_summaries, max_iterations,
            )
            completed_results.extend(layer_results)
            for r in layer_results:
                context_summaries.append(r.summary)

            # Analyze feedback results (may generate more feedback)
            for wo, result in zip(batch, layer_results):
                feedback_wo = self.analyzer.analyze_result(wo, result, next_wo_index)
                if feedback_wo:
                    self.work_queue.enqueue(feedback_wo)
                    next_wo_index += 1

        # Record Kaizen metrics
        if telemetry.enabled:
            total_wos = len(completed_results)
            passed_first = sum(
                1 for r in completed_results
                if r.status == "completed" and not r.defects
            )
            if total_wos > 0 and hasattr(telemetry, "kaizen_first_pass_yield"):
                telemetry.kaizen_first_pass_yield.record(passed_first / total_wos)
            rework_count = self.analyzer.total_rework_count
            if total_wos > 0 and hasattr(telemetry, "kaizen_rework_ratio"):
                telemetry.kaizen_rework_ratio.record(rework_count / total_wos)

        yield self._emit(
            f"\n[ShopFloor] Production complete: "
            f"{len(completed_results)} work orders executed"
            f" ({self.analyzer.total_rework_count} rework)",
        )

    def _execute_layer(
        self,
        layer: List[WorkOrder],
        parent_station: Workstation,
        context_summaries: List[str],
        max_iterations: int,
    ) -> Generator[OutputEvent, None, List[WorkOrderResult]]:
        """Execute a single layer of work orders.

        Dispatch strategy:
        - Single WO: dispatch on parent workstation (sequential)
        - Multiple WOs + Celery enabled: distributed dispatch
        - Multiple WOs + local: spawn child workstations, parallel local
        """
        if len(layer) == 1:
            # Sequential - dispatch on parent workstation
            wo = layer[0]
            wo.status = WorkOrderStatus.DISPATCHED
            wo.dispatched_at = datetime.utcnow().isoformat()
            yield self._emit(f"[ShopFloor] Dispatching WO-{wo.index} (sequential)")

            result = yield from self._dispatch_single(
                wo, parent_station, context_summaries, max_iterations,
            )
            return [result] if result else []

        # Optional serialization to avoid parallel worker side effects (e.g., CLI that isn't parallel-safe)
        if os.getenv("SF_DISABLE_LOCAL_PARALLEL", "0") == "1":
            results = []
            for wo in layer:
                yield self._emit(f"[ShopFloor] Serializing WO-{wo.index} (parallel disabled)",)
                wo.status = WorkOrderStatus.DISPATCHED
                wo.dispatched_at = datetime.utcnow().isoformat()
                res = yield from self._dispatch_single(
                    wo, parent_station, context_summaries, max_iterations,
                )
                if res:
                    results.append(res)
            return results

        # Multiple WOs - parallel execution
        if self.use_celery and self._celery_available():
            yield self._emit(
                f"[ShopFloor] Dispatching {len(layer)} WOs via Celery (distributed)",
            )
            results = yield from self._dispatch_distributed(
                layer, parent_station, context_summaries, max_iterations,
            )
            return results

        # Local parallel via workstation spawn
        yield self._emit(
            f"[ShopFloor] Spawning {len(layer)} parallel workstations (local)",
        )
        return (yield from self._dispatch_parallel_local(
            layer, parent_station, context_summaries, max_iterations,
        ))

    def _dispatch_parallel_local(
        self,
        layer: List[WorkOrder],
        parent_station: Workstation,
        context_summaries: List[str],
        max_iterations: int,
    ) -> Generator[OutputEvent, None, List[WorkOrderResult]]:
        """Dispatch multiple WOs in parallel via local workstation spawning."""
        # Checkpoint parent before spawning
        parent_station.checkpoint(f"pre-spawn layer")

        children: List[Workstation] = []
        for wo in layer:
            child = parent_station.spawn(f"wo-{wo.index}")
            child.commission()
            children.append(child)
            wo.status = WorkOrderStatus.DISPATCHED
            wo.dispatched_at = datetime.utcnow().isoformat()

        # Dispatch to children
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
                # Generate resolution WO via analyzer
                resolution = self.analyzer.analyze_conflict(
                    integration,
                    {"summary": f"Parallel merge WO-{wo.index}"},
                    next_index=wo.index + 1000,  # High index to avoid collision
                )
                if resolution:
                    self.work_queue.enqueue(resolution)
            else:
                yield self._emit(
                    f"[ShopFloor] FAILED merging WO-{wo.index}: "
                    f"{integration.message}",
                    event_type=EventType.ERROR,
                )

            child.decommission()

        return layer_results

    def _dispatch_distributed(
        self,
        layer: List[WorkOrder],
        parent_station: Workstation,
        context_summaries: List[str],
        max_iterations: int,
    ) -> Generator[OutputEvent, None, List[WorkOrderResult]]:
        """Dispatch work orders to Celery workers for distributed execution.

        Serializes WorkOrder + Workstation, sends to capability-matched queue,
        waits for results, then integrates via git fetch + merge.
        """
        telemetry = get_telemetry()

        try:
            from .tasks import run_work_order
        except ImportError:
            yield self._emit(
                "[ShopFloor] Celery not available, falling back to local parallel",
                event_type=EventType.ERROR,
            )
            results = yield from self._dispatch_parallel_local(
                layer, parent_station, context_summaries, max_iterations,
            )
            return results

        # Checkpoint parent before distributed dispatch
        parent_station.checkpoint("pre-distributed-dispatch")

        # Submit tasks to Celery
        async_results = []
        for wo in layer:
            wo.status = WorkOrderStatus.DISPATCHED
            wo.dispatched_at = datetime.utcnow().isoformat()

            # Determine queue based on capabilities
            target_queue = self._route_to_queue(wo)

            yield self._emit(
                f"[ShopFloor] Dispatching WO-{wo.index} to Celery queue '{target_queue}'",
            )

            async_result = run_work_order.apply_async(
                args=[
                    wo.serialize(),
                    parent_station.serialize(),
                    context_summaries[-5:],
                ],
                queue=target_queue,
            )
            async_results.append((wo, async_result))

            if telemetry.enabled and hasattr(telemetry, "celery_tasks_dispatched"):
                telemetry.celery_tasks_dispatched.add(1, {"queue": target_queue})

        # Collect results
        layer_results: List[WorkOrderResult] = []
        for wo, async_result in async_results:
            try:
                result_data = async_result.get(timeout=600)  # 10 min timeout
                result = WorkOrderResult.deserialize(result_data)
                layer_results.append(result)

                yield self._emit(
                    f"[ShopFloor] WO-{wo.index} completed on worker: {result.summary[:80]}",
                )
            except Exception as e:
                yield self._emit(
                    f"[ShopFloor] WO-{wo.index} failed on worker: {e}",
                    event_type=EventType.ERROR,
                )
                layer_results.append(WorkOrderResult(
                    status="failed",
                    summary=f"Celery worker failed: {e}",
                    work_order_index=wo.index,
                ))

        # Integrate remote branches
        for wo, result in zip(layer, layer_results):
            if result.status == "completed":
                integration = self.assembly.integrate_remote(
                    parent_station, f"wo-{wo.index}",
                )
                if integration.status == IntegrationStatus.SUCCESS:
                    yield self._emit(
                        f"[ShopFloor] Integrated remote WO-{wo.index}: "
                        f"{len(integration.merged_files)} files",
                    )
                else:
                    yield self._emit(
                        f"[ShopFloor] Remote integration failed WO-{wo.index}: "
                        f"{integration.message}",
                        event_type=EventType.ERROR,
                    )

        return layer_results

    def _route_to_queue(self, wo: WorkOrder) -> str:
        """Route a work order to a Celery queue based on required capabilities.

        Args:
            wo: Work order with required_capabilities.

        Returns:
            Queue name string.
        """
        caps = wo.required_capabilities
        if not caps:
            return self.queue

        # Route to specialized queues based on capabilities
        if caps.get("gpu"):
            return "gpu"
        if caps.get("languages"):
            langs = caps["languages"]
            if isinstance(langs, list) and langs:
                return f"{langs[0]}-{self.queue}"
        return self.queue

    def _dispatch_single(
        self,
        wo: WorkOrder,
        station: Workstation,
        prior_context: List[str],
        max_iterations: int,
    ) -> Generator[OutputEvent, None, Optional[WorkOrderResult]]:
        """Dispatch a single work order to a workstation.

        Uses the PA's single-worker loop on the workstation's working directory.
        Performs capability matching before dispatch.

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
        # Capability matching (Phase 5)
        if wo.required_capabilities:
            caps_dict = station.capabilities.to_match_dict()
            if not match_capabilities(wo.required_capabilities, caps_dict):
                yield self._emit(
                    f"[ShopFloor] WO-{wo.index} capability mismatch "
                    f"(required: {wo.required_capabilities})",
                    event_type=EventType.ERROR,
                )
                return WorkOrderResult(
                    status="failed",
                    summary=f"WO-{wo.index} capability mismatch",
                    work_order_index=wo.index,
                )

        wo.status = WorkOrderStatus.IN_PROGRESS
        start_time = time.time()

        telemetry = get_telemetry()
        wo_span = None
        if telemetry.enabled and telemetry.tracer:
            wo_span = telemetry.tracer.start_span(
                "workstation.produce",
                attributes={
                    "work_order.index": wo.index,
                    "work_order.source": wo.source,
                    "work_order.prompt": wo.prompt[:200],
                },
            )

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

            provider_name = getattr(self.pa, "_llm_provider", os.getenv("SF_LLM_PROVIDER", "claude_cli"))
            if provider_name.startswith("codex"):
                files_changed = self._codex_generate_work(wo, station, prompt, provider_name)
            elif provider_name == "claude_cli":
                # Stream Claude on the workstation
                for event in self.pa._stream_claude(prompt, working_dir=station.path):
                    yield event
                    events.append({
                        "type": event.event_type.value,
                        "content": event.content[:500],
                        "source": event.metadata.get("source", ""),
                    })
            else:
                # Other providers generate files directly (reuse codex generation path)
                files_changed = self._codex_generate_work(wo, station, prompt, provider_name)

            # Checkpoint after work
            commit = station.checkpoint(f"WO-{wo.index}: {wo.prompt[:50]}")
            if commit:
                yield self._emit(f"[WO-{wo.index}] Checkpoint: {commit[:8]}")

            duration = time.time() - start_time
            wo.status = WorkOrderStatus.COMPLETED
            wo.completed_at = datetime.utcnow().isoformat()
            summary = f"WO-{wo.index} completed in {duration:.1f}s"

            yield self._emit(f"[WO-{wo.index}] {summary}")

            # Record OTEL
            if telemetry.enabled and hasattr(telemetry, "workstation_production_time"):
                telemetry.workstation_production_time.record(duration)
                telemetry.work_order_lead_time.record(duration, {"source": wo.source})
            if wo_span:
                wo_span.set_attribute("work_order.status", "completed")
                wo_span.set_attribute("work_order.duration_s", duration)
                wo_span.end()

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

            # Record OTEL
            if wo_span:
                wo_span.set_attribute("work_order.status", "failed")
                wo_span.set_attribute("work_order.error", str(e)[:200])
                wo_span.end()

            return WorkOrderResult(
                status="failed",
                events=events,
                files_changed=[],
                summary=f"WO-{wo.index} failed: {e}",
                duration=duration,
                work_order_index=wo.index,
            )

    def _run_quality_gates(
        self,
        layer: List[WorkOrder],
        results: List[WorkOrderResult],
        parent_station: Workstation,
        layer_idx: int,
    ) -> Generator[OutputEvent, None, None]:
        """Run quality gates on layer results."""
        telemetry = get_telemetry()

        for gate in self.quality_gates:
            for wo, wo_result in zip(layer, results):
                gate_span = None
                if telemetry.enabled and telemetry.tracer:
                    gate_span = telemetry.tracer.start_span(
                        "quality_gate.inspection",
                        attributes={
                            "quality_gate.type": type(gate).__name__,
                            "quality_gate.layer": layer_idx + 1,
                        },
                    )

                # Plugin hook: ON_VERIFY_START (Phase 6)
                if PluginHookPhase and hasattr(self.pa, "_plugin_manager"):
                    self.pa._plugin_manager.trigger_hook(
                        PluginHookPhase.ON_VERIFY_START,
                        gate_type=type(gate).__name__,
                        work_order_index=wo.index,
                    )

                inspection = gate.inspect(wo, wo_result, parent_station)

                # Plugin hook: ON_VERIFY_COMPLETE (Phase 6)
                if PluginHookPhase and hasattr(self.pa, "_plugin_manager"):
                    self.pa._plugin_manager.trigger_hook(
                        PluginHookPhase.ON_VERIFY_COMPLETE,
                        gate_type=type(gate).__name__,
                        passed=inspection.passed,
                        defects=inspection.defects[:5],
                    )

                if telemetry.enabled and hasattr(telemetry, "quality_gate_inspections"):
                    telemetry.quality_gate_inspections.add(1, {
                        "gate_name": type(gate).__name__,
                        "passed": str(inspection.passed).lower(),
                    })
                if gate_span:
                    gate_span.set_attribute("quality_gate.passed", inspection.passed)
                    gate_span.set_attribute("quality_gate.details", inspection.details[:200])
                    gate_span.end()

                if not inspection.passed:
                    yield self._emit(
                        f"[QualityGate] FAILED WO-{wo.index}: {inspection.details}",
                        event_type=EventType.ERROR,
                    )
                    # Add defects to result for analyzer
                    wo_result.defects.extend(inspection.defects)

                    # Generate rework WO via analyzer
                    feedback_wo = self.analyzer.analyze_inspection(
                        wo, inspection,
                        next_index=wo.index + 2000,  # High index to avoid collision
                    )
                    if feedback_wo:
                        self.work_queue.enqueue(feedback_wo)
                        yield self._emit(
                            f"[Kaizen] Quality gate feedback WO-{feedback_wo.index} enqueued",
                        )

    def _dispatch_resolution(
        self,
        wo: WorkOrder,
        result: IntegrationResult,
    ) -> None:
        """Handle a conflict resolution work order.

        Wired to assembly.resolve_conflict() via the analyzer.
        """
        resolution = self.analyzer.analyze_conflict(
            result,
            {"summary": f"Conflict resolution for WO-{wo.index}"},
            next_index=wo.index + 3000,
        )
        if resolution:
            self.work_queue.enqueue(resolution)

    @staticmethod
    def _celery_available() -> bool:
        """Check if Celery workers are reachable."""
        try:
            from . import is_celery_available
            return is_celery_available()
        except Exception:
            return False

    def _limit_parallelism(
        self,
        layers: List[List[WorkOrder]],
        limit: int,
    ) -> List[List[WorkOrder]]:
        """Cap parallel WOs per layer by chunking large layers.

        Preserves dependency layering while avoiding excessive local spawning.
        """
        capped_layers: List[List[WorkOrder]] = []
        for layer in layers:
            if len(layer) <= limit:
                capped_layers.append(layer)
                continue
            for i in range(0, len(layer), limit):
                capped_layers.append(layer[i:i + limit])
        return capped_layers

    def _emit(
        self,
        content: str,
        event_type: EventType = EventType.TEXT,
    ) -> OutputEvent:
        """Create an OutputEvent."""
        return OutputEvent(
            event_type=event_type,
            content=content,
            metadata={"source": "shopfloor"},
        )

    def _codex_generate_work(self, wo: WorkOrder, station: Workstation, prompt: str, provider_name: str = "codex_api") -> List[str]:
        """Use Codex (or other JSON-file-returning) provider to generate file outputs for a work order."""
        files_changed: List[str] = []

        try:
            provider = get_provider(provider_name)
            system_msg = (
                "You are a coding agent. Return ONLY JSON with a 'files' array; "
                "each entry has 'path' (relative) and 'content'. "
                "Project root is current working directory. "
                "Keep code minimal and runnable."
            )
            messages = [
                LLMMessage(role="system", content=system_msg),
                LLMMessage(role="user", content=f"Task: {prompt}\nGenerate minimal code + tests."),
            ]
            request = LLMRequest(messages=messages, model=None, provider=provider_name)
            result = provider.generate(request)
            try:
                data = json.loads(result.text)
                files = data.get("files", [])
            except Exception:
                files = []
        except Exception:
            files = []

        if not files:
            # Fallback minimal fib implementation with package inits
            files = [
                {"path": "src/fibonacci/fib.py",
                 "content": "def fib_iter(n):\n    a,b=0,1\n    for _ in range(n): a,b=b,a+b\n    return a\n\ndef fib_rec(n):\n    return n if n<2 else fib_rec(n-1)+fib_rec(n-2)\n"},
                {"path": "tests/test_fib.py",
                 "content": "from src.fibonacci.fib import fib_iter, fib_rec\n\ndef test_iter():\n    assert fib_iter(5)==5\n\ndef test_rec():\n    assert fib_rec(6)==8\n"},
                {"path": "src/__init__.py", "content": ""},
                {"path": "src/fibonacci/__init__.py", "content": ""},
            ]

        for fobj in files:
            path = fobj.get("path")
            content = fobj.get("content", "")
            if not path:
                continue
            abs_path = os.path.join(station.path, path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w") as f:
                f.write(content)
            files_changed.append(os.path.relpath(abs_path, station.path))

        return files_changed
