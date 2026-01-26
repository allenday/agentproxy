"""
Stub Celery Worker
==================

Standalone Celery app with a lightweight stub task for integration testing
worker parallelism.  The stub task sleeps for a configurable duration and
returns a MilestoneResult-compatible dict.

Used by ``test_fib_parallel_workers.py`` — does NOT require the full
PA + Gemini pipeline.

Usage (manual):
    celery -A tests.integration._stub_worker worker -c 1 -Q default
"""

import os
import time

from celery import Celery

REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")

app = Celery("stub_worker", broker=REDIS_URL, backend=REDIS_URL)
app.conf.update(
    worker_concurrency=1,
    task_acks_late=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)


@app.task(name="stub.run_milestone", bind=True)
def run_milestone(self, prompt, working_dir, session_id, milestone_index, context):
    """Stub task that sleeps and returns a MilestoneResult-compatible dict.

    The sleep duration is read from ``context["sleep"]`` (default 1.0s).
    """
    sleep_time = float(context.get("sleep", 1.0))
    time.sleep(sleep_time)
    return {
        "status": "completed",
        "events": [],
        "files_changed": [f"file_{milestone_index}.py"],
        "summary": f"Milestone {milestone_index}: {prompt[:50]}",
        "duration": sleep_time,
        "milestone_index": milestone_index,
    }
