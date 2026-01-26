"""
Coordinator
===========

Orchestrates multi-worker task execution by decomposing a task into
milestones and dispatching each one sequentially to a Celery worker.

The generator-based interface is preserved: ``run_task_multi_worker()``
yields ``OutputEvent`` objects exactly like the single-worker path.
"""

import re
import time
from typing import TYPE_CHECKING, Any, Dict, Generator, List

from ..models import EventType, OutputEvent
from ..telemetry import get_telemetry
from .models import Milestone, MilestoneResult, deserialize_output_event

if TYPE_CHECKING:
    from ..pa import PA


# Default poll interval (seconds) when waiting for a Celery result
_POLL_INTERVAL = 2.0

# Maximum time to wait for a single milestone (seconds)
_MILESTONE_TIMEOUT = 1800  # 30 minutes

# Regex to extract dependency annotations like (depends: 1, 3) from milestone text
_DEPENDS_RE = re.compile(r"\(depends:\s*([\d,\s]+)\)\s*$", re.IGNORECASE)


class Coordinator:
    """Orchestrate task decomposition and sequential milestone dispatch.

    Args:
        pa: The parent PA instance (used for task breakdown and context).
        queue: Celery queue name for milestone dispatch.
    """

    def __init__(self, pa: "PA", queue: str = "default"):
        self.pa = pa
        self.queue = queue

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_task_multi_worker(
        self, task: str, max_iterations: int = 100
    ) -> Generator[OutputEvent, None, None]:
        """Decompose *task* into milestones, dispatch via layered execution.

        This is the multi-worker counterpart to ``PA._run_task_single_worker``.
        Milestones are topologically sorted into execution layers based on
        dependency annotations. Independent milestones within a layer are
        dispatched in parallel via ``celery.group()``. Sequential execution
        is the degenerate case (linear deps produce N layers of 1).
        """
        yield self._emit(
            "[Coordinator] Decomposing task into milestones...",
            EventType.THINKING,
        )
        breakdown_text = self.pa.agent.generate_task_breakdown(task)

        milestones = self._parse_milestones_with_deps(breakdown_text)
        if not milestones:
            milestones = [Milestone(index=0, prompt=task, depends_on=[])]

        yield self._emit(
            f"[Coordinator] {len(milestones)} milestone(s) planned",
            EventType.TEXT,
        )

        yield from self._dispatch(milestones)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_milestones(breakdown_text: str) -> List[str]:
        """Extract milestone strings from a markdown task breakdown.

        The breakdown returned by ``PAAgent.generate_task_breakdown`` is a
        markdown string with ``- [ ]`` checklist items.  We extract the
        text from each checklist item as a milestone prompt.
        """
        milestones: List[str] = []
        for line in breakdown_text.splitlines():
            # Match markdown checklist items: - [ ] description
            match = re.match(r"^\s*[-*]\s*\[[ x]?\]\s*(.+)$", line, re.IGNORECASE)
            if match:
                text = match.group(1).strip()
                if text:
                    milestones.append(text)
        return milestones

    @staticmethod
    def _parse_milestones_with_deps(breakdown_text: str) -> List[Milestone]:
        """Extract milestones with dependency annotations from a breakdown.

        Parses ``(depends: N, M)`` suffixes from checklist items. The numbers
        in the annotation are **1-based** step numbers (matching the user-facing
        ``Step N`` labels); they are converted to 0-based indices internally.

        If **no** annotations are found anywhere in the breakdown, falls back
        to a sequential chain where each milestone depends on its predecessor.
        """
        milestones: List[Milestone] = []
        any_annotation = False

        for line in breakdown_text.splitlines():
            match = re.match(r"^\s*[-*]\s*\[[ x]?\]\s*(.+)$", line, re.IGNORECASE)
            if not match:
                continue
            text = match.group(1).strip()
            if not text:
                continue

            depends_on: List[int] = []
            dep_match = _DEPENDS_RE.search(text)
            if dep_match:
                any_annotation = True
                raw_deps = dep_match.group(1)
                for num_str in raw_deps.split(","):
                    num_str = num_str.strip()
                    if num_str.isdigit():
                        # Convert 1-based step number to 0-based index
                        depends_on.append(int(num_str) - 1)
                text = _DEPENDS_RE.sub("", text).strip()

            milestones.append(
                Milestone(index=len(milestones), prompt=text, depends_on=depends_on)
            )

        # Fallback: if no annotations found, create sequential chain
        if milestones and not any_annotation:
            for m in milestones:
                if m.index > 0:
                    m.depends_on = [m.index - 1]

        return milestones

    @staticmethod
    def _build_layers(milestones: List[Milestone]) -> List[List[Milestone]]:
        """Topologically sort milestones into execution layers (Kahn's algorithm).

        Each layer contains milestones whose dependencies are fully satisfied
        by prior layers. Cycles are broken by releasing the lowest-index
        milestone.
        """
        remaining = {m.index for m in milestones}
        completed: set = set()
        milestone_map = {m.index: m for m in milestones}
        layers: List[List[Milestone]] = []

        while remaining:
            ready = [
                i for i in remaining
                if all(d in completed for d in milestone_map[i].depends_on)
            ]
            if not ready:
                # Break cycles by releasing the lowest-index milestone
                ready = [min(remaining)]
            layers.append([milestone_map[i] for i in sorted(ready)])
            completed.update(ready)
            remaining -= set(ready)

        return layers

    def _dispatch(
        self, milestones: List[Milestone]
    ) -> Generator[OutputEvent, None, None]:
        """Unified dispatch: parallel layers via group(), single via direct call.

        Sequential execution is the degenerate form — when every milestone
        depends on its predecessor, each layer has exactly one milestone.
        """
        from .tasks import run_milestone

        telemetry = get_telemetry()
        layers = self._build_layers(milestones)
        total = len(milestones)
        context: Dict[str, Any] = {"prior_summary": "", "prior_files_changed": []}
        milestone_results: Dict[int, MilestoneResult] = {}

        for layer_idx, layer in enumerate(layers):
            yield self._emit(
                f"[Coordinator] Layer {layer_idx + 1}/{len(layers)}: "
                f"{len(layer)} milestone(s)",
                EventType.TEXT,
            )

            if len(layer) == 1:
                # Single milestone — dispatch directly (no group overhead)
                m = layer[0]
                ctx = self._build_milestone_context(m, milestone_results, context)

                if telemetry.enabled:
                    telemetry.milestones_dispatched.add(1)

                async_result = run_milestone.apply_async(
                    args=[m.prompt, self.pa.working_dir, self.pa.session_id, m.index, ctx],
                    queue=self.queue,
                )
                yield from self._poll_result(async_result, m.index, total)

                raw = async_result.get(timeout=_MILESTONE_TIMEOUT)
                result = MilestoneResult.from_dict(raw)
                milestone_results[m.index] = result

                if telemetry.enabled:
                    telemetry.milestones_completed.add(1, {"status": result.status})
                    telemetry.milestone_duration.record(result.duration)

                yield from self._replay_events(m.index, result, total)
                context = self._update_context(context, result)
            else:
                # Multiple milestones — use Celery group()
                from celery import group as celery_group

                tasks = []
                for m in layer:
                    ctx = self._build_milestone_context(m, milestone_results, context)
                    tasks.append(
                        run_milestone.s(
                            m.prompt, self.pa.working_dir, self.pa.session_id, m.index, ctx
                        )
                    )

                    if telemetry.enabled:
                        telemetry.milestones_dispatched.add(1)

                group_result = celery_group(tasks).apply_async(queue=self.queue)
                yield from self._poll_group(group_result, layer, total)

                raw_results = group_result.get(timeout=_MILESTONE_TIMEOUT)

                layer_results: List[MilestoneResult] = []
                for raw, m in zip(raw_results, layer):
                    result = MilestoneResult.from_dict(raw)
                    milestone_results[m.index] = result
                    layer_results.append(result)

                    if telemetry.enabled:
                        telemetry.milestones_completed.add(1, {"status": result.status})
                        telemetry.milestone_duration.record(result.duration)

                    yield from self._replay_events(m.index, result, total)

                # File conflict detection
                conflicts = self._detect_file_conflicts(layer_results)
                if conflicts:
                    yield self._emit(
                        f"[Coordinator] Conflicts detected: {conflicts}",
                        EventType.TEXT,
                    )
                    yield from self._reconcile_conflicts(conflicts, layer_results, context)

                for result in layer_results:
                    context = self._update_context(context, result)

        yield self._emit(
            f"[Coordinator] All {total} milestones dispatched",
            EventType.COMPLETED,
        )

    @staticmethod
    def _build_milestone_context(
        milestone: Milestone,
        milestone_results: Dict[int, MilestoneResult],
        global_ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build context dict from a milestone's specific dependencies."""
        ctx = dict(global_ctx)
        dep_summaries: List[str] = []
        dep_files: List[str] = []
        for dep_idx in milestone.depends_on:
            if dep_idx in milestone_results:
                r = milestone_results[dep_idx]
                dep_summaries.append(r.summary)
                dep_files.extend(r.files_changed)
        if dep_summaries:
            ctx["prior_summary"] = "\n- ".join(dep_summaries)
            ctx["prior_files_changed"] = list(
                set(dep_files + ctx.get("prior_files_changed", []))
            )
        return ctx

    def _poll_group(
        self, group_result, layer: List[Milestone], total: int
    ) -> Generator[OutputEvent, None, None]:
        """Poll a Celery GroupResult, yielding per-milestone progress."""
        start = time.time()
        while not group_result.ready():
            elapsed = time.time() - start
            if elapsed > _MILESTONE_TIMEOUT:
                yield self._emit(
                    "[Coordinator] Layer timed out",
                    EventType.ERROR,
                )
                return
            done = sum(1 for r in group_result.results if r.ready())
            yield self._emit(
                f"[Coordinator] {done}/{len(layer)} complete ({elapsed:.0f}s)",
                EventType.THINKING,
            )
            time.sleep(_POLL_INTERVAL)

    @staticmethod
    def _detect_file_conflicts(
        results: List[MilestoneResult],
    ) -> Dict[str, List[int]]:
        """Detect files modified by more than one milestone in the same layer."""
        file_owners: Dict[str, List[int]] = {}
        for r in results:
            for f in r.files_changed:
                file_owners.setdefault(f, []).append(r.milestone_index)
        return {f: owners for f, owners in file_owners.items() if len(owners) > 1}

    def _reconcile_conflicts(
        self,
        conflicts: Dict[str, List[int]],
        layer_results: List[MilestoneResult],
        context: Dict[str, Any],
    ) -> Generator[OutputEvent, None, None]:
        """Dispatch a reconciliation milestone for conflicting file changes."""
        from .tasks import run_milestone

        conflict_desc = "\n".join(
            f"- {path}: milestones {owners}" for path, owners in conflicts.items()
        )
        summaries = "\n".join(
            f"- Milestone {r.milestone_index}: {r.summary}" for r in layer_results
        )
        prompt = (
            f"Parallel agents modified the same files. Reconcile:\n\n"
            f"Conflicts:\n{conflict_desc}\n\nSummaries:\n{summaries}\n\n"
            f"Merge changes coherently and ensure code compiles/passes tests."
        )
        async_result = run_milestone.apply_async(
            args=[prompt, self.pa.working_dir, self.pa.session_id, -1, context],
            queue=self.queue,
        )
        yield from self._poll_result(async_result, -1, 1)
        raw = async_result.get(timeout=_MILESTONE_TIMEOUT)
        result = MilestoneResult.from_dict(raw)
        yield from self._replay_events(-1, result, 1)

    def _replay_events(
        self, milestone_index: int, result: MilestoneResult, total: int
    ) -> Generator[OutputEvent, None, None]:
        """Replay worker events and emit milestone status."""
        for evt_dict in result.events:
            yield deserialize_output_event(evt_dict)

        yield self._emit(
            f"[Coordinator] Milestone {milestone_index + 1} {result.status} "
            f"({result.duration:.1f}s, {len(result.files_changed)} files changed)",
            EventType.TEXT,
        )

        if result.status == "error":
            yield self._emit(
                f"[Coordinator] Milestone {milestone_index + 1} errored: {result.summary}",
                EventType.ERROR,
            )

    def _poll_result(
        self, async_result, milestone_index: int, total: int
    ) -> Generator[OutputEvent, None, None]:
        """Poll a Celery AsyncResult, yielding progress events."""
        start = time.time()
        while not async_result.ready():
            elapsed = time.time() - start
            if elapsed > _MILESTONE_TIMEOUT:
                yield self._emit(
                    f"[Coordinator] Milestone {milestone_index + 1}/{total} timed out after {elapsed:.0f}s",
                    EventType.ERROR,
                )
                return
            yield self._emit(
                f"[Coordinator] Milestone {milestone_index + 1}/{total} running ({elapsed:.0f}s elapsed)...",
                EventType.THINKING,
            )
            time.sleep(_POLL_INTERVAL)

    @staticmethod
    def _update_context(
        context: Dict[str, Any], result: MilestoneResult
    ) -> Dict[str, Any]:
        """Accumulate context from a completed milestone for the next one."""
        prior_files = list(set(context.get("prior_files_changed", []) + result.files_changed))
        prior_summary = context.get("prior_summary", "")
        if result.summary:
            prior_summary += f"\n- {result.summary}" if prior_summary else result.summary
        return {
            "prior_summary": prior_summary,
            "prior_files_changed": prior_files,
        }

    @staticmethod
    def _emit(
        content: str,
        event_type: EventType = EventType.TEXT,
        source: str = "coordinator",
    ) -> OutputEvent:
        return OutputEvent(
            event_type=event_type, content=content, metadata={"source": source}
        )
