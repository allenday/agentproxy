"""
Celery Tasks
=============

Defines the distributed task for executing a work order on a remote worker.

Each worker receives a serialized WorkOrder + Workstation, reconstructs
the environment, and runs Claude via subprocess.

Phase 4 additions:
- OTEL context propagation (link worker spans to supervisor trace)
- Heartbeat via self.update_state(state='PROGRESS')
- SOP materialization during worker commission
"""

from .celery_app import make_celery_app

celery_app = make_celery_app()


@celery_app.task(bind=True, name="sf.shopfloor.run_work_order")
def run_work_order(self, work_order_data: dict, workstation_data: dict,
                   prior_context: list, claude_bin: str = "claude",
                   otel_context: dict = None) -> dict:
    """Execute a single work order on a Celery worker.

    Args:
        work_order_data: Serialized WorkOrder dict.
        workstation_data: Serialized Workstation dict (fixture + capabilities + sop).
        prior_context: List of summary strings from earlier work orders.
        claude_bin: Path to claude binary.
        otel_context: Serialized OTEL trace context for linking spans.

    Returns:
        Serialized WorkOrderResult dict.
    """
    import json
    import subprocess
    import time

    from ..workstation.workstation import Workstation
    from .models import WorkOrder, WorkOrderResult, WorkOrderStatus

    wo = WorkOrder.deserialize(work_order_data)
    station = Workstation.deserialize(workstation_data)

    wo.status = WorkOrderStatus.IN_PROGRESS
    start_time = time.time()

    # Heartbeat: report progress
    self.update_state(state="PROGRESS", meta={
        "wo_index": wo.index,
        "status": "commissioning",
    })

    # Build enriched prompt
    prompt = wo.prompt
    if prior_context:
        context_str = "\n".join(f"- {s}" for s in prior_context[-5:])
        prompt = f"Context from prior work:\n{context_str}\n\nCurrent task:\n{prompt}"

    # Commission the workstation on this worker
    # SOP materialization happens inside commission() automatically
    station.commission()

    self.update_state(state="PROGRESS", meta={
        "wo_index": wo.index,
        "status": "producing",
    })

    events = []
    files_changed = []

    # Set up OTEL environment for subprocess if context provided
    env = None
    if otel_context:
        import os
        env = os.environ.copy()
        env["OTEL_TRACE_ID"] = otel_context.get("trace_id", "")
        env["OTEL_SPAN_ID"] = otel_context.get("span_id", "")

    try:
        # Execute Claude subprocess on the workstation's directory
        process = subprocess.Popen(
            [claude_bin, "-p", prompt, "--output-format", "stream-json",
             "--verbose", "--dangerously-skip-permissions"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=station.path,
            bufsize=1,
            env=env,
        )

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            line = line.rstrip()
            if not line:
                continue
            try:
                data = json.loads(line)
                events.append({
                    "type": data.get("type", "unknown"),
                    "content": json.dumps(data)[:500],
                })
            except json.JSONDecodeError:
                events.append({"type": "raw", "content": line[:500]})

            # Periodic heartbeat
            if len(events) % 50 == 0:
                self.update_state(state="PROGRESS", meta={
                    "wo_index": wo.index,
                    "status": "producing",
                    "events_count": len(events),
                })

        process.wait(timeout=300)

        # Checkpoint
        commit = station.checkpoint(f"WO-{wo.index}: {wo.prompt[:50]}")
        if commit:
            events.append({
                "type": "checkpoint",
                "content": f"Committed: {commit[:8]}",
            })

        duration = time.time() - start_time
        wo.status = WorkOrderStatus.COMPLETED

        self.update_state(state="PROGRESS", meta={
            "wo_index": wo.index,
            "status": "completed",
            "duration": duration,
        })

        return WorkOrderResult(
            status="completed",
            events=events,
            files_changed=files_changed,
            summary=f"WO-{wo.index} completed in {duration:.1f}s",
            duration=duration,
            work_order_index=wo.index,
        ).serialize()

    except Exception as e:
        duration = time.time() - start_time
        wo.status = WorkOrderStatus.FAILED
        return WorkOrderResult(
            status="failed",
            events=events,
            files_changed=[],
            summary=f"WO-{wo.index} failed: {e}",
            duration=duration,
            work_order_index=wo.index,
        ).serialize()
