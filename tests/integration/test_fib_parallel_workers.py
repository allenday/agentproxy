"""
Integration tests for parallel worker dispatch with fibonacci-style milestones.

Verifies real Celery + Redis infrastructure with actual worker processes:

  - Single worker (1 process): tasks execute sequentially
  - Dual workers (2 processes): independent tasks execute in parallel

The fibonacci-style milestone structure:
    Layer 0: [project_setup]               (1 task  - sequential)
    Layer 1: [fib_iterative, fib_recursive] (2 tasks - PARALLEL)
    Layer 2: [write_tests]                 (1 task  - sequential)

Prerequisites:
  - Redis running at localhost:6379 (or TEST_REDIS_URL env var)
  - celery and redis packages installed
  - No GEMINI_API_KEY needed (uses stub task, not real PA)
"""

import os
import subprocess
import sys
import time

import pytest

# ---------------------------------------------------------------------------
# Skip entire module if celery/redis not installed
# ---------------------------------------------------------------------------

try:
    import celery as _celery_mod  # noqa: F401
    import redis as _redis_mod
except ImportError:
    pytest.skip("celery and/or redis not installed", allow_module_level=True)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")

# Each stub task sleeps this long.  Keep short for fast tests,
# long enough that timing assertions are reliable.
TASK_SLEEP = 1.5

# Maximum time to wait for workers to come online
WORKER_STARTUP_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _redis_ping() -> bool:
    """Return True if Redis is reachable."""
    try:
        r = _redis_mod.Redis.from_url(REDIS_URL, socket_timeout=2)
        r.ping()
        return True
    except (_redis_mod.ConnectionError, _redis_mod.TimeoutError):
        return False


def _flush_redis():
    """Flush the test Redis DB to start clean."""
    r = _redis_mod.Redis.from_url(REDIS_URL, socket_timeout=2)
    r.flushdb()


def _start_workers(n: int, name_prefix: str = "test") -> list:
    """Start *n* Celery workers as subprocesses using the stub worker module.

    Each worker runs with ``-c 1`` (1 prefork process) so that *n* workers
    provide *n* units of concurrency.
    """
    env = {
        **os.environ,
        "TEST_REDIS_URL": REDIS_URL,
        "PYTHONPATH": REPO_ROOT + ":" + os.environ.get("PYTHONPATH", ""),
    }
    workers = []
    for i in range(n):
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "celery",
                "-A", "tests.integration._stub_worker",
                "worker",
                "--loglevel=warning",
                "-c", "1",
                "-n", f"{name_prefix}-{i}@%h",
                "-Q", "default",
                "--without-heartbeat",
                "--without-mingle",
                "--without-gossip",
                "-P", "solo",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=REPO_ROOT,
        )
        workers.append(proc)
    return workers


def _wait_for_workers(app, expected: int, timeout: float = WORKER_STARTUP_TIMEOUT) -> bool:
    """Poll ``celery inspect ping`` until *expected* workers are online."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            inspect = app.control.inspect()
            pong = inspect.ping()
            if pong and len(pong) >= expected:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _stop_workers(workers: list):
    """Terminate and reap worker subprocesses."""
    for proc in workers:
        proc.terminate()
    for proc in workers:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def redis_available():
    """Skip the entire module if Redis is not reachable."""
    if not _redis_ping():
        pytest.skip(f"Redis not available at {REDIS_URL}")
    _flush_redis()


@pytest.fixture(scope="module")
def stub_app(redis_available):
    """Import the stub worker's Celery app and task."""
    # Ensure the repo root is on sys.path so the subprocess import also works
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    from tests.integration._stub_worker import app, run_milestone
    return app, run_milestone


# ---------------------------------------------------------------------------
# Tests: Single worker — sequential execution
# ---------------------------------------------------------------------------

class TestSingleWorkerSequential:
    """With 1 worker (solo pool, concurrency=1), tasks execute sequentially."""

    @pytest.fixture(autouse=True, scope="class")
    def _workers(self, stub_app):
        """Start 1 worker before the class, stop after."""
        app, _ = stub_app
        _flush_redis()
        workers = _start_workers(1, name_prefix="single")
        online = _wait_for_workers(app, expected=1)
        if not online:
            _stop_workers(workers)
            pytest.skip("Worker did not come online")
        yield workers
        _stop_workers(workers)

    def test_group_sequential_with_one_worker(self, stub_app):
        """celery.group of 2 tasks takes ~2x sleep with 1 worker."""
        _, run_milestone = stub_app
        from celery import group

        ctx = {"sleep": TASK_SLEEP}
        g = group(
            run_milestone.s("fib_iterative", "/tmp", "test", 1, ctx),
            run_milestone.s("fib_recursive", "/tmp", "test", 2, ctx),
        )

        start = time.time()
        result = g.apply_async(queue="default")
        raw_results = result.get(timeout=60)
        elapsed = time.time() - start

        assert len(raw_results) == 2
        assert all(r["status"] == "completed" for r in raw_results)
        # Sequential: should be at least 2x sleep time (minus small tolerance)
        assert elapsed >= TASK_SLEEP * 1.8, (
            f"Too fast ({elapsed:.1f}s) for sequential — "
            f"expected >= {TASK_SLEEP * 1.8:.1f}s"
        )

    def test_diamond_sequential_with_one_worker(self, stub_app):
        """Fibonacci diamond (4 milestones) takes ~4x sleep with 1 worker."""
        _, run_milestone = stub_app
        from celery import group

        ctx = {"sleep": TASK_SLEEP}

        start = time.time()

        # Layer 0: project setup (1 task)
        r0 = run_milestone.apply_async(
            args=["project_setup", "/tmp", "test", 0, ctx],
            queue="default",
        )
        res0 = r0.get(timeout=60)
        assert res0["status"] == "completed"

        # Layer 1: fib_iterative + fib_recursive (2 tasks — dispatched as group)
        g1 = group(
            run_milestone.s("fib_iterative", "/tmp", "test", 1, ctx),
            run_milestone.s("fib_recursive", "/tmp", "test", 2, ctx),
        )
        r1 = g1.apply_async(queue="default")
        res1 = r1.get(timeout=60)
        assert len(res1) == 2
        assert all(r["status"] == "completed" for r in res1)

        # Layer 2: write tests (1 task)
        r3 = run_milestone.apply_async(
            args=["write_tests", "/tmp", "test", 3, ctx],
            queue="default",
        )
        res3 = r3.get(timeout=60)
        assert res3["status"] == "completed"

        elapsed = time.time() - start
        # All sequential with 1 worker: ~4x sleep
        assert elapsed >= TASK_SLEEP * 3.5, (
            f"Too fast ({elapsed:.1f}s) for 4 sequential tasks — "
            f"expected >= {TASK_SLEEP * 3.5:.1f}s"
        )


# ---------------------------------------------------------------------------
# Tests: Dual workers — parallel execution
# ---------------------------------------------------------------------------

class TestDualWorkerParallel:
    """With 2 workers, independent tasks in a group execute in parallel."""

    @pytest.fixture(autouse=True, scope="class")
    def _workers(self, stub_app):
        """Start 2 workers before the class, stop after."""
        app, _ = stub_app
        _flush_redis()
        workers = _start_workers(2, name_prefix="dual")
        online = _wait_for_workers(app, expected=2)
        if not online:
            _stop_workers(workers)
            pytest.skip("Workers did not come online")
        yield workers
        _stop_workers(workers)

    def test_group_parallel_with_two_workers(self, stub_app):
        """celery.group of 2 tasks takes ~1x sleep with 2 workers."""
        _, run_milestone = stub_app
        from celery import group

        ctx = {"sleep": TASK_SLEEP}
        g = group(
            run_milestone.s("fib_iterative", "/tmp", "test", 1, ctx),
            run_milestone.s("fib_recursive", "/tmp", "test", 2, ctx),
        )

        start = time.time()
        result = g.apply_async(queue="default")
        raw_results = result.get(timeout=60)
        elapsed = time.time() - start

        assert len(raw_results) == 2
        assert all(r["status"] == "completed" for r in raw_results)
        # Parallel: should be close to 1x sleep time (plus overhead)
        assert elapsed < TASK_SLEEP * 1.8, (
            f"Too slow ({elapsed:.1f}s) for parallel — "
            f"expected < {TASK_SLEEP * 1.8:.1f}s"
        )

    def test_diamond_parallel_with_two_workers(self, stub_app):
        """Fibonacci diamond: layer 1 runs in parallel, saving ~1x sleep."""
        _, run_milestone = stub_app
        from celery import group

        ctx = {"sleep": TASK_SLEEP}

        start = time.time()

        # Layer 0: project setup (1 task)
        r0 = run_milestone.apply_async(
            args=["project_setup", "/tmp", "test", 0, ctx],
            queue="default",
        )
        res0 = r0.get(timeout=60)
        assert res0["status"] == "completed"

        # Layer 1: fib_iterative + fib_recursive (2 tasks — PARALLEL)
        g1 = group(
            run_milestone.s("fib_iterative", "/tmp", "test", 1, ctx),
            run_milestone.s("fib_recursive", "/tmp", "test", 2, ctx),
        )
        r1 = g1.apply_async(queue="default")
        res1 = r1.get(timeout=60)
        assert len(res1) == 2
        assert all(r["status"] == "completed" for r in res1)

        # Layer 2: write tests (1 task)
        r3 = run_milestone.apply_async(
            args=["write_tests", "/tmp", "test", 3, ctx],
            queue="default",
        )
        res3 = r3.get(timeout=60)
        assert res3["status"] == "completed"

        elapsed = time.time() - start
        # Diamond with 2 workers: ~3x sleep (layer1 runs in parallel)
        # versus ~4x sleep with 1 worker
        assert elapsed < TASK_SLEEP * 3.5, (
            f"Diamond took {elapsed:.1f}s — expected < {TASK_SLEEP * 3.5:.1f}s "
            f"with 2-worker parallelism"
        )

    def test_results_carry_milestone_metadata(self, stub_app):
        """Stub task returns proper MilestoneResult-compatible dicts."""
        _, run_milestone = stub_app
        ctx = {"sleep": 0.1}  # Fast for this test

        r = run_milestone.apply_async(
            args=["fib_iterative", "/tmp", "test", 42, ctx],
            queue="default",
        )
        result = r.get(timeout=30)

        assert result["status"] == "completed"
        assert result["milestone_index"] == 42
        assert "file_42.py" in result["files_changed"]
        assert "fib_iterative" in result["summary"]
        assert result["duration"] >= 0.1
