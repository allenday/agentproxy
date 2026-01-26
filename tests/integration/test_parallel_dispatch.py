"""
Integration tests for parallel multi-agent dispatch.

Tests the unified dispatch path: parallel layers via celery.group(),
single-milestone layers via direct apply_async, conflict reconciliation,
and the sequential fallback when no dependency annotations are present.

These tests mock Celery internals and do NOT require a running Redis/worker.
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

from agentproxy.coordinator.coordinator import Coordinator
from agentproxy.coordinator.models import Milestone, MilestoneResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_result(milestone_index, files_changed=None):
    """Create a MagicMock that behaves like an AsyncResult returning MilestoneResult."""
    result = MilestoneResult(
        status="completed",
        events=[],
        files_changed=files_changed or [],
        summary=f"Milestone {milestone_index} done",
        duration=1.0,
        milestone_index=milestone_index,
    )
    mock = MagicMock()
    mock.ready.return_value = True
    mock.get.return_value = result.to_dict()
    return mock


def _make_coordinator():
    """Create a Coordinator with a mocked PA."""
    mock_pa = MagicMock()
    mock_pa.working_dir = "/tmp/test"
    mock_pa.session_id = "test-session"
    return Coordinator(mock_pa)


def _make_mock_run_milestone():
    """Create a mock run_milestone task with apply_async and s methods."""
    mock_task = MagicMock()
    mock_task.s = lambda *args, **kw: MagicMock(args=args)
    return mock_task


@pytest.fixture(autouse=True)
def _mock_tasks_module():
    """Inject a mock tasks module so the `from .tasks import run_milestone`
    inside _dispatch() and _reconcile_conflicts() resolves without celery.
    Also injects a mock celery module if celery is not installed."""
    saved = {}

    # Mock the tasks module
    tasks_key = "agentproxy.coordinator.tasks"
    saved[tasks_key] = sys.modules.get(tasks_key)
    mock_module = MagicMock()
    sys.modules[tasks_key] = mock_module

    # Mock celery module if not installed
    celery_key = "celery"
    celery_installed = celery_key in sys.modules and sys.modules[celery_key] is not None
    if not celery_installed:
        try:
            import celery  # noqa: F401
            celery_installed = True
        except ImportError:
            pass

    if not celery_installed:
        saved[celery_key] = sys.modules.get(celery_key)
        mock_celery = MagicMock()
        sys.modules[celery_key] = mock_celery

    yield mock_module

    # Restore
    for key, original in saved.items():
        if original is not None:
            sys.modules[key] = original
        else:
            sys.modules.pop(key, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParallelLayerUsesGroup:
    """Verify that a layer with >1 milestone uses celery.group()."""

    def test_parallel_layer_uses_group(self, _mock_tasks_module):
        coord = _make_coordinator()

        milestones = [
            Milestone(index=0, prompt="Setup"),
            Milestone(index=1, prompt="API", depends_on=[0]),
            Milestone(index=2, prompt="Tests", depends_on=[0]),
            Milestone(index=3, prompt="Integration", depends_on=[1, 2]),
        ]

        apply_async_calls = []
        group_apply_calls = []

        def mock_apply_async(args=None, queue=None, **kw):
            apply_async_calls.append(args[3])  # milestone_index
            return _make_mock_result(args[3])

        mock_group_result = MagicMock()
        mock_group_result.ready.return_value = True
        mock_group_result.get.return_value = [
            _make_mock_result(1).get.return_value,
            _make_mock_result(2).get.return_value,
        ]
        mock_group_result.results = [
            MagicMock(ready=MagicMock(return_value=True)),
            MagicMock(ready=MagicMock(return_value=True)),
        ]

        def mock_group_constructor(tasks):
            mock_group_obj = MagicMock()
            def ga(queue=None, **kw):
                group_apply_calls.append(len(tasks))
                return mock_group_result
            mock_group_obj.apply_async = ga
            return mock_group_obj

        # Configure the mock tasks module
        _mock_tasks_module.run_milestone.apply_async = mock_apply_async
        _mock_tasks_module.run_milestone.s = lambda *args, **kw: MagicMock(args=args)

        with patch("celery.group", side_effect=mock_group_constructor):
            events = list(coord._dispatch(milestones))

        # Layer 0 (Setup) and Layer 2 (Integration) go via direct apply_async
        assert 0 in apply_async_calls
        assert 3 in apply_async_calls
        # Layer 1 (API, Tests) goes via group
        assert len(group_apply_calls) == 1
        assert group_apply_calls[0] == 2  # 2 tasks in the group


class TestSingleMilestoneLayerSkipsGroup:
    """Verify that a layer with exactly 1 milestone uses direct apply_async."""

    def test_single_milestone_layer_skips_group(self, _mock_tasks_module):
        coord = _make_coordinator()

        milestones = [
            Milestone(index=0, prompt="Only step"),
        ]

        apply_async_calls = []

        def mock_apply_async(args=None, queue=None, **kw):
            apply_async_calls.append(args[3])
            return _make_mock_result(args[3])

        _mock_tasks_module.run_milestone.apply_async = mock_apply_async

        events = list(coord._dispatch(milestones))

        assert apply_async_calls == [0]


class TestReconciliationOnConflict:
    """Verify that overlapping files_changed triggers reconciliation."""

    def test_reconciliation_on_conflict(self, _mock_tasks_module):
        coord = _make_coordinator()

        milestones = [
            Milestone(index=0, prompt="A"),
            Milestone(index=1, prompt="B"),
        ]

        # Both milestones modify the same file
        result_a = MilestoneResult(
            status="completed", events=[], files_changed=["shared.py"],
            summary="A done", duration=1.0, milestone_index=0,
        )
        result_b = MilestoneResult(
            status="completed", events=[], files_changed=["shared.py"],
            summary="B done", duration=1.0, milestone_index=1,
        )

        mock_group_result = MagicMock()
        mock_group_result.ready.return_value = True
        mock_group_result.get.return_value = [result_a.to_dict(), result_b.to_dict()]
        mock_group_result.results = [
            MagicMock(ready=MagicMock(return_value=True)),
            MagicMock(ready=MagicMock(return_value=True)),
        ]

        reconcile_calls = []

        def mock_apply_async(args=None, queue=None, **kw):
            milestone_idx = args[3]
            if milestone_idx == -1:
                reconcile_calls.append(args[0])  # prompt
            return _make_mock_result(milestone_idx)

        def mock_group_constructor(tasks):
            mock_obj = MagicMock()
            mock_obj.apply_async = lambda queue=None, **kw: mock_group_result
            return mock_obj

        _mock_tasks_module.run_milestone.apply_async = mock_apply_async
        _mock_tasks_module.run_milestone.s = lambda *args, **kw: MagicMock(args=args)

        with patch("celery.group", side_effect=mock_group_constructor):
            events = list(coord._dispatch(milestones))

        # A reconciliation milestone should have been dispatched
        assert len(reconcile_calls) == 1
        assert "Reconcile" in reconcile_calls[0]


class TestNoDepsProducesSequential:
    """Verify that a breakdown without annotations produces N layers of 1."""

    def test_no_deps_produces_sequential(self, _mock_tasks_module):
        coord = _make_coordinator()
        coord.pa.agent.generate_task_breakdown.return_value = (
            "- [ ] Step 1: Setup\n"
            "- [ ] Step 2: Build\n"
            "- [ ] Step 3: Test\n"
        )

        dispatched = []

        def mock_apply_async(args=None, queue=None, **kw):
            dispatched.append(args[3])
            return _make_mock_result(args[3])

        _mock_tasks_module.run_milestone.apply_async = mock_apply_async

        events = list(coord.run_task_multi_worker("Build something"))

        # Sequential: each milestone dispatched individually (no group)
        assert dispatched == [0, 1, 2]
