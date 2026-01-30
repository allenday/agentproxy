# sf/ — Core Package

Purpose: PA supervisor core, CLI/server entry points, and shared runtime services.

Main entry points:
- `sf.cli:main` (`sf` CLI)
- `sf.server:app` (FastAPI server)
- `sf.pa.PA` (supervisor loop)

Where to look:
- **SOP + fixtures:** `sf/workstation/` (see `sf/workstation/AGENTS.md`)
- **Telemetry:** `sf/telemetry.py` and `sf/event_processors/`

## Files

| File | Role |
|------|------|
| `pa.py` | **PA** supervisor loop. `run_task()` yields `OutputEvent`s. Branches to `ShopFloor.produce()` when `use_shopfloor=True`. |
| `pa_agent.py` | Gemini client. `generate_task_breakdown()` → numbered steps with `(depends: N)` (the BOM format `parse_work_orders()` expects). |
| `pa_memory.py` | Session persistence: task breakdown, summaries, best practices. |
| `models.py` | `OutputEvent` (dataclass), `EventType`, `ControllerState`. |
| `cli.py` | `sf` entry point. `--workorder-type` activates ShopFloor. `--workorder-content` overrides task text. `--sop NAME` sets workstation SOP (defaults to `v0` when workorder-type is set). |
| `server.py` | FastAPI. `/task` SSE stream. `/webhook/{github,jira,alert}` enqueue to `webhook_queue`. `/queue` inspects. `/produce` drains through ShopFloor. |
| `process_manager.py` | Spawns `claude` subprocess, streams JSON events. |
| `telemetry.py` | OTEL singleton via `get_telemetry()`. |
| `function_executor.py` | Executes PA agent functions (send_to_claude, verify, etc.). |
| `display.py` | Terminal rendering with source-colored prefixes (`SOURCE_PREFIXES` dict). |

## PA → ShopFloor Bridge

```
PA.__init__(use_shopfloor=True, sop_name="v0")
  → create_workstation(sop_name="v0")   # SOP attached to station
  → ShopFloor(pa=self)                  # lazy import avoids circular dep

PA.run_task()
  → _setup_task_breakdown()             # Gemini produces BOM
  → if _use_shopfloor:
      → shopfloor.produce(task, breakdown_text, max_iterations)
```

## OutputEvent Convention

Source identity goes in `metadata`, not as a field:
```python
OutputEvent(event_type=..., content=..., metadata={"source": "pa"})
```
`OutputEvent` has no `source` field. Passing `source=` as a kwarg will crash.

## Telemetry Rule

OTEL must never break the app. All telemetry calls: `try: ... except Exception: pass`.
