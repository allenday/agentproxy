# sf/shopfloor/ — Parallel Orchestration

Purpose: Route and execute Work Orders across worktrees with quality gates and Kaizen feedback.

Main entry points:
- `ShopFloor.produce()` in `shopfloor.py`
- `parse_work_orders()` / `build_layers()` in `routing.py`

Where to look:
- **SOP + fixtures:** `sf/workstation/` (commissioning + verification)
- **Telemetry:** `sf/telemetry.py` and `sf/event_processors/`

BOM decomposition → layer routing → parallel dispatch → quality gates → assembly → Kaizen rework.

## Pipeline

```
ShopFloor.produce(task, breakdown_text, max_iterations)
  1. parse_work_orders(breakdown_text)   → List[WorkOrder]       routing.py
  2. build_layers(work_orders)           → List[List[WO]]        routing.py
  3. _execute_with_kaizen(layers)                                 shopfloor.py
       per layer:
         single WO  → _dispatch_single()   → Claude on parent station
         multi WO   → _dispatch_parallel()  → spawn child worktrees
         quality gates (see sf/workstation/AGENTS.md)
         assembly: merge child branches into parent
       Kaizen: re-queue failed WOs as feedback, repeat up to max_cycles
```

## Files

| File | Role |
|------|------|
| `shopfloor.py` | `ShopFloor` — produce loop, dispatch, Kaizen. |
| `routing.py` | `parse_work_orders()` + `build_layers()` (topological sort by `depends_on`). |
| `assembly.py` | `AssemblyStation` — merges worktree branches via `git merge`. |
| `models.py` | `WorkOrder`, `WorkOrderResult`, `WorkOrderStatus` (all Pydantic). |
| `queue.py` | `WorkOrderQueue` — priority heap (feedback=0, telemetry=1, external=2, decomposition=3). |
| `dispatch.py` | `DispatchStrategy` ABC. Implementations: `DirectClaudeDispatch`, `CeleryDispatch`, `WorkerPADispatch`. |
| `analyzer.py` | `ResultAnalyzer` — post-production analysis. |
| `tasks.py` | Celery task definitions. |
| `worker_cli.py` | `sf-worker` entry point. |

## BOM Format

Gemini output that `parse_work_orders()` consumes (1-indexed input → 0-indexed WorkOrders):
```
1. Create project scaffold
2. Implement fibonacci logic (depends: 1)
3. Set up testing framework (depends: 1)
4. Write and run tests (depends: 2, 3)
```

`build_layers()` yields: Layer 1: [WO-0] → Layer 2: [WO-1, WO-2] (parallel) → Layer 3: [WO-3].
