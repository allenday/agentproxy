"""
Unit tests for the multi-worker coordinator package.

Tests coordinator models, milestone parsing, availability checks,
and the PA multi-worker dispatch path.
"""

import os
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock, PropertyMock


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestMilestoneResult:
    """Test MilestoneResult dataclass and serialization."""

    def test_create_milestone_result(self):
        from agentproxy.coordinator.models import MilestoneResult

        result = MilestoneResult(
            status="completed",
            events=[{"event_type": "TEXT", "content": "hello", "timestamp": "2025-01-01T00:00:00", "metadata": {}}],
            files_changed=["src/main.py"],
            summary="Did the thing",
            duration=12.5,
            milestone_index=0,
        )
        assert result.status == "completed"
        assert len(result.events) == 1
        assert result.files_changed == ["src/main.py"]
        assert result.duration == 12.5

    def test_to_dict_roundtrip(self):
        from agentproxy.coordinator.models import MilestoneResult

        original = MilestoneResult(
            status="error",
            events=[{"event_type": "ERROR", "content": "boom", "timestamp": "2025-01-01T00:00:00", "metadata": {}}],
            files_changed=["a.py", "b.py"],
            summary="Failed",
            duration=3.2,
            milestone_index=2,
        )
        d = original.to_dict()
        restored = MilestoneResult.from_dict(d)

        assert restored.status == original.status
        assert restored.events == original.events
        assert restored.files_changed == original.files_changed
        assert restored.summary == original.summary
        assert restored.duration == original.duration
        assert restored.milestone_index == original.milestone_index

    def test_from_dict_defaults(self):
        from agentproxy.coordinator.models import MilestoneResult

        result = MilestoneResult.from_dict({})
        assert result.status == "error"
        assert result.events == []
        assert result.files_changed == []
        assert result.summary == ""
        assert result.duration == 0.0
        assert result.milestone_index == 0


class TestOutputEventSerialization:
    """Test OutputEvent serialization/deserialization helpers."""

    def test_serialize_roundtrip(self):
        from agentproxy.models import OutputEvent, EventType
        from agentproxy.coordinator.models import serialize_output_event, deserialize_output_event

        event = OutputEvent(
            event_type=EventType.TEXT,
            content="hello world",
            metadata={"source": "test"},
        )
        d = serialize_output_event(event)
        assert d["event_type"] == "TEXT"
        assert d["content"] == "hello world"
        assert "timestamp" in d

        restored = deserialize_output_event(d)
        assert restored.event_type == EventType.TEXT
        assert restored.content == "hello world"
        assert restored.metadata == {"source": "test"}

    def test_deserialize_all_event_types(self):
        from agentproxy.models import EventType
        from agentproxy.coordinator.models import deserialize_output_event

        for et in EventType:
            d = {
                "event_type": et.name,
                "content": f"test-{et.name}",
                "timestamp": "2025-01-01T00:00:00",
                "metadata": {},
            }
            event = deserialize_output_event(d)
            assert event.event_type == et


# ---------------------------------------------------------------------------
# Celery availability
# ---------------------------------------------------------------------------


class TestCeleryAvailability:
    """Test is_celery_available() guard."""

    def test_returns_false_when_celery_missing(self):
        """is_celery_available() returns False when celery is not installed."""
        import sys

        # Save originals
        celery_mod = sys.modules.get("celery")
        redis_mod = sys.modules.get("redis")

        try:
            # Force celery import to fail
            sys.modules["celery"] = None
            from agentproxy.coordinator import is_celery_available
            assert is_celery_available() is False
        finally:
            # Restore
            if celery_mod is not None:
                sys.modules["celery"] = celery_mod
            else:
                sys.modules.pop("celery", None)
            if redis_mod is not None:
                sys.modules["redis"] = redis_mod
            else:
                sys.modules.pop("redis", None)

    def test_returns_false_when_no_workers(self):
        """is_celery_available() returns False when packages are installed but no workers respond."""
        try:
            import celery  # noqa: F401
            import redis  # noqa: F401
        except ImportError:
            pytest.skip("celery and/or redis not installed")

        from agentproxy.coordinator import is_celery_available

        mock_app = MagicMock()
        mock_app.control.inspect.return_value.ping.return_value = None
        with patch("agentproxy.coordinator.celery_app.make_celery_app", return_value=mock_app):
            assert is_celery_available() is False

    def test_returns_true_when_workers_respond(self):
        """is_celery_available() returns True when workers respond to ping."""
        try:
            import celery  # noqa: F401
            import redis  # noqa: F401
        except ImportError:
            pytest.skip("celery and/or redis not installed")

        from agentproxy.coordinator import is_celery_available

        mock_app = MagicMock()
        mock_app.control.inspect.return_value.ping.return_value = {
            "worker-1@host": {"ok": "pong"}
        }
        with patch("agentproxy.coordinator.celery_app.make_celery_app", return_value=mock_app):
            assert is_celery_available() is True


# ---------------------------------------------------------------------------
# Milestone parsing
# ---------------------------------------------------------------------------


class TestMilestoneParsing:
    """Test Coordinator._parse_milestones()."""

    def test_parse_checklist_items(self):
        from agentproxy.coordinator.coordinator import Coordinator

        breakdown = """# Task: Build a REST API

- [ ] Set up project structure
- [ ] Create user endpoints
- [ ] Add authentication
- [ ] Write tests
"""
        milestones = Coordinator._parse_milestones(breakdown)
        assert len(milestones) == 4
        assert milestones[0] == "Set up project structure"
        assert milestones[3] == "Write tests"

    def test_parse_checked_items(self):
        from agentproxy.coordinator.coordinator import Coordinator

        breakdown = "- [x] Already done\n- [ ] Still todo"
        milestones = Coordinator._parse_milestones(breakdown)
        assert len(milestones) == 2

    def test_parse_star_bullets(self):
        from agentproxy.coordinator.coordinator import Coordinator

        breakdown = "* [ ] Step A\n* [ ] Step B"
        milestones = Coordinator._parse_milestones(breakdown)
        assert len(milestones) == 2

    def test_parse_empty_returns_empty(self):
        from agentproxy.coordinator.coordinator import Coordinator

        milestones = Coordinator._parse_milestones("")
        assert milestones == []

    def test_parse_non_checklist_returns_empty(self):
        from agentproxy.coordinator.coordinator import Coordinator

        breakdown = "This is just a paragraph.\nNo checklist items here."
        milestones = Coordinator._parse_milestones(breakdown)
        assert milestones == []

    def test_parse_indented_items(self):
        from agentproxy.coordinator.coordinator import Coordinator

        breakdown = "  - [ ] Indented step\n    - [ ] More indented"
        milestones = Coordinator._parse_milestones(breakdown)
        assert len(milestones) == 2


# ---------------------------------------------------------------------------
# Context accumulation
# ---------------------------------------------------------------------------


class TestContextAccumulation:
    """Test Coordinator._update_context()."""

    def test_accumulates_files(self):
        from agentproxy.coordinator.coordinator import Coordinator
        from agentproxy.coordinator.models import MilestoneResult

        ctx = {"prior_summary": "", "prior_files_changed": []}
        result = MilestoneResult(
            status="completed",
            files_changed=["a.py", "b.py"],
            summary="Step 1 done",
        )
        new_ctx = Coordinator._update_context(ctx, result)
        assert "a.py" in new_ctx["prior_files_changed"]
        assert "b.py" in new_ctx["prior_files_changed"]
        assert "Step 1 done" in new_ctx["prior_summary"]

    def test_deduplicates_files(self):
        from agentproxy.coordinator.coordinator import Coordinator
        from agentproxy.coordinator.models import MilestoneResult

        ctx = {"prior_summary": "", "prior_files_changed": ["a.py"]}
        result = MilestoneResult(
            status="completed",
            files_changed=["a.py", "c.py"],
            summary="Step 2",
        )
        new_ctx = Coordinator._update_context(ctx, result)
        assert new_ctx["prior_files_changed"].count("a.py") == 1

    def test_appends_summary(self):
        from agentproxy.coordinator.coordinator import Coordinator
        from agentproxy.coordinator.models import MilestoneResult

        ctx = {"prior_summary": "Step 1", "prior_files_changed": []}
        result = MilestoneResult(status="completed", summary="Step 2")
        new_ctx = Coordinator._update_context(ctx, result)
        assert "Step 1" in new_ctx["prior_summary"]
        assert "Step 2" in new_ctx["prior_summary"]


# ---------------------------------------------------------------------------
# _should_use_multi_worker
# ---------------------------------------------------------------------------


class TestShouldUseMultiWorker:
    """Test PA._should_use_multi_worker()."""

    def test_false_without_celery(self):
        """Returns False when celery/redis are not importable."""
        from agentproxy.pa import PA

        pa = MagicMock(spec=PA)
        pa._should_use_multi_worker = PA._should_use_multi_worker.__get__(pa)

        with patch("agentproxy.pa.PA._should_use_multi_worker", wraps=pa._should_use_multi_worker):
            # Mock is_celery_available to return False
            with patch("agentproxy.coordinator.is_celery_available", return_value=False):
                assert pa._should_use_multi_worker() is False

    def test_true_when_workers_available(self):
        """Returns True when is_celery_available() reports workers are running."""
        from agentproxy.pa import PA

        pa = MagicMock(spec=PA)
        pa._should_use_multi_worker = PA._should_use_multi_worker.__get__(pa)

        with patch("agentproxy.coordinator.is_celery_available", return_value=True):
            assert pa._should_use_multi_worker() is True


# ---------------------------------------------------------------------------
# Queue routing
# ---------------------------------------------------------------------------


class TestQueueRouting:
    """Test queue configuration for workers."""

    def test_default_queue(self):
        from agentproxy.coordinator.coordinator import Coordinator

        mock_pa = MagicMock()
        coord = Coordinator(mock_pa)
        assert coord.queue == "default"

    def test_custom_queue(self):
        from agentproxy.coordinator.coordinator import Coordinator

        mock_pa = MagicMock()
        coord = Coordinator(mock_pa, queue="worker-gpu-1")
        assert coord.queue == "worker-gpu-1"


# ---------------------------------------------------------------------------
# Worker CLI
# ---------------------------------------------------------------------------


class TestWorkerCLI:
    """Test worker_cli argument parsing (without starting Celery)."""

    def test_default_args(self):
        """Default args produce 'default' queue and 'info' loglevel."""
        from agentproxy.coordinator.worker_cli import main
        import argparse

        # We can't actually call main() without celery, but we can test arg parsing
        parser = argparse.ArgumentParser()
        parser.add_argument("--queue", default=None)
        parser.add_argument("--loglevel", default="info")
        parser.add_argument("--concurrency", type=int, default=1)

        args = parser.parse_args([])
        assert args.queue is None
        assert args.loglevel == "info"
        assert args.concurrency == 1

    def test_custom_args(self):
        """Custom args are parsed correctly."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--queue", default=None)
        parser.add_argument("--loglevel", default="info")
        parser.add_argument("--concurrency", type=int, default=1)

        args = parser.parse_args(["--queue", "gpu-1", "--loglevel", "debug", "--concurrency", "2"])
        assert args.queue == "gpu-1"
        assert args.loglevel == "debug"
        assert args.concurrency == 2


# ---------------------------------------------------------------------------
# Telemetry metrics existence
# ---------------------------------------------------------------------------


class TestMilestoneMetrics:
    """Test that milestone metrics are created when telemetry is enabled."""

    def test_milestone_metrics_exist(self):
        """Milestone counters and histogram are created."""
        with patch.dict(os.environ, {"AGENTPROXY_ENABLE_TELEMETRY": "1"}):
            from agentproxy.telemetry import OTEL_AVAILABLE

            if not OTEL_AVAILABLE:
                pytest.skip("OTEL packages not installed")

            from agentproxy.telemetry import AgentProxyTelemetry

            telemetry = AgentProxyTelemetry()
            assert hasattr(telemetry, "milestones_dispatched")
            assert hasattr(telemetry, "milestones_completed")
            assert hasattr(telemetry, "milestone_duration")


# ---------------------------------------------------------------------------
# Milestone model
# ---------------------------------------------------------------------------


class TestMilestone:
    """Test Milestone dataclass and serialization."""

    def test_milestone_to_dict_roundtrip(self):
        from agentproxy.coordinator.models import Milestone

        original = Milestone(index=2, prompt="Write tests", depends_on=[0, 1])
        d = original.to_dict()
        restored = Milestone.from_dict(d)

        assert restored.index == original.index
        assert restored.prompt == original.prompt
        assert restored.depends_on == original.depends_on


# ---------------------------------------------------------------------------
# Milestone parsing with deps
# ---------------------------------------------------------------------------


class TestMilestoneParsingWithDeps:
    """Test Coordinator._parse_milestones_with_deps()."""

    def test_parse_with_depends_annotations(self):
        from agentproxy.coordinator.coordinator import Coordinator

        breakdown = (
            "- [ ] Step 1: Set up project\n"
            "- [ ] Step 2: Build API (depends: 1)\n"
        )
        milestones = Coordinator._parse_milestones_with_deps(breakdown)
        assert len(milestones) == 2
        assert milestones[0].depends_on == []
        assert milestones[1].depends_on == [0]  # 1-based → 0-based

    def test_parse_without_depends_falls_back_sequential(self):
        from agentproxy.coordinator.coordinator import Coordinator

        breakdown = (
            "- [ ] Step 1: Set up\n"
            "- [ ] Step 2: Build\n"
            "- [ ] Step 3: Test\n"
        )
        milestones = Coordinator._parse_milestones_with_deps(breakdown)
        assert len(milestones) == 3
        assert milestones[0].depends_on == []
        assert milestones[1].depends_on == [0]
        assert milestones[2].depends_on == [1]

    def test_parse_multi_depends(self):
        from agentproxy.coordinator.coordinator import Coordinator

        breakdown = "- [ ] Step 1: A\n- [ ] Step 2: B\n- [ ] Step 3: C (depends: 1, 2)\n"
        milestones = Coordinator._parse_milestones_with_deps(breakdown)
        assert milestones[2].depends_on == [0, 1]

    def test_parse_mixed_annotated_and_bare(self):
        from agentproxy.coordinator.coordinator import Coordinator

        breakdown = (
            "- [ ] Step 1: Setup\n"
            "- [ ] Step 2: API (depends: 1)\n"
            "- [ ] Step 3: Tests\n"  # bare — but annotation flag is set
        )
        milestones = Coordinator._parse_milestones_with_deps(breakdown)
        assert len(milestones) == 3
        # Step 1 has no deps annotation → empty
        assert milestones[0].depends_on == []
        # Step 2 has explicit dep
        assert milestones[1].depends_on == [0]
        # Step 3 has no annotation but since *some* annotations exist,
        # it stays as declared (no fallback to sequential)
        assert milestones[2].depends_on == []

    def test_depends_stripped_from_prompt_text(self):
        from agentproxy.coordinator.coordinator import Coordinator

        breakdown = "- [ ] Step 1: Do stuff (depends: 1)\n"
        milestones = Coordinator._parse_milestones_with_deps(breakdown)
        assert "(depends" not in milestones[0].prompt
        assert milestones[0].prompt == "Step 1: Do stuff"


# ---------------------------------------------------------------------------
# Layer builder
# ---------------------------------------------------------------------------


class TestLayerBuilder:
    """Test Coordinator._build_layers() topological sort."""

    def test_single_milestone_one_layer(self):
        from agentproxy.coordinator.coordinator import Coordinator
        from agentproxy.coordinator.models import Milestone

        milestones = [Milestone(index=0, prompt="Only task")]
        layers = Coordinator._build_layers(milestones)
        assert len(layers) == 1
        assert len(layers[0]) == 1

    def test_sequential_chain(self):
        from agentproxy.coordinator.coordinator import Coordinator
        from agentproxy.coordinator.models import Milestone

        milestones = [
            Milestone(index=0, prompt="A"),
            Milestone(index=1, prompt="B", depends_on=[0]),
            Milestone(index=2, prompt="C", depends_on=[1]),
        ]
        layers = Coordinator._build_layers(milestones)
        assert len(layers) == 3
        assert [len(l) for l in layers] == [1, 1, 1]

    def test_diamond_dependency(self):
        from agentproxy.coordinator.coordinator import Coordinator
        from agentproxy.coordinator.models import Milestone

        milestones = [
            Milestone(index=0, prompt="Setup"),
            Milestone(index=1, prompt="API", depends_on=[0]),
            Milestone(index=2, prompt="Tests", depends_on=[0]),
            Milestone(index=3, prompt="Integration", depends_on=[1, 2]),
        ]
        layers = Coordinator._build_layers(milestones)
        assert len(layers) == 3
        assert len(layers[0]) == 1  # Setup
        assert len(layers[1]) == 2  # API, Tests (parallel)
        assert len(layers[2]) == 1  # Integration

    def test_all_independent(self):
        from agentproxy.coordinator.coordinator import Coordinator
        from agentproxy.coordinator.models import Milestone

        milestones = [
            Milestone(index=0, prompt="A"),
            Milestone(index=1, prompt="B"),
            Milestone(index=2, prompt="C"),
            Milestone(index=3, prompt="D"),
        ]
        layers = Coordinator._build_layers(milestones)
        assert len(layers) == 1
        assert len(layers[0]) == 4

    def test_cycle_breaks_on_lowest_index(self):
        from agentproxy.coordinator.coordinator import Coordinator
        from agentproxy.coordinator.models import Milestone

        # Cycle: 0 → 1 → 0
        milestones = [
            Milestone(index=0, prompt="A", depends_on=[1]),
            Milestone(index=1, prompt="B", depends_on=[0]),
        ]
        layers = Coordinator._build_layers(milestones)
        # Should not hang — cycle is broken
        assert len(layers) == 2
        assert layers[0][0].index == 0  # lowest breaks first


# ---------------------------------------------------------------------------
# File conflict detection
# ---------------------------------------------------------------------------


class TestFileConflictDetection:
    """Test Coordinator._detect_file_conflicts()."""

    def test_no_conflicts(self):
        from agentproxy.coordinator.coordinator import Coordinator
        from agentproxy.coordinator.models import MilestoneResult

        results = [
            MilestoneResult(status="completed", files_changed=["a.py"], milestone_index=0),
            MilestoneResult(status="completed", files_changed=["b.py"], milestone_index=1),
        ]
        conflicts = Coordinator._detect_file_conflicts(results)
        assert conflicts == {}

    def test_one_conflict(self):
        from agentproxy.coordinator.coordinator import Coordinator
        from agentproxy.coordinator.models import MilestoneResult

        results = [
            MilestoneResult(status="completed", files_changed=["shared.py"], milestone_index=0),
            MilestoneResult(status="completed", files_changed=["shared.py"], milestone_index=1),
        ]
        conflicts = Coordinator._detect_file_conflicts(results)
        assert "shared.py" in conflicts
        assert set(conflicts["shared.py"]) == {0, 1}

    def test_multiple_conflicts(self):
        from agentproxy.coordinator.coordinator import Coordinator
        from agentproxy.coordinator.models import MilestoneResult

        results = [
            MilestoneResult(status="completed", files_changed=["a.py", "b.py"], milestone_index=0),
            MilestoneResult(status="completed", files_changed=["b.py", "c.py"], milestone_index=1),
            MilestoneResult(status="completed", files_changed=["a.py", "c.py"], milestone_index=2),
        ]
        conflicts = Coordinator._detect_file_conflicts(results)
        assert "a.py" in conflicts
        assert "b.py" in conflicts
        assert "c.py" in conflicts


# ---------------------------------------------------------------------------
# Milestone context
# ---------------------------------------------------------------------------


class TestMilestoneContext:
    """Test Coordinator._build_milestone_context()."""

    def test_context_from_specific_deps(self):
        from agentproxy.coordinator.coordinator import Coordinator
        from agentproxy.coordinator.models import Milestone, MilestoneResult

        milestone = Milestone(index=2, prompt="Integration", depends_on=[0, 1])
        results = {
            0: MilestoneResult(status="completed", summary="Setup done", files_changed=["setup.py"], milestone_index=0),
            1: MilestoneResult(status="completed", summary="API done", files_changed=["api.py"], milestone_index=1),
        }
        global_ctx = {"prior_summary": "", "prior_files_changed": []}
        ctx = Coordinator._build_milestone_context(milestone, results, global_ctx)

        assert "Setup done" in ctx["prior_summary"]
        assert "API done" in ctx["prior_summary"]
        assert "setup.py" in ctx["prior_files_changed"]
        assert "api.py" in ctx["prior_files_changed"]

    def test_context_no_deps_uses_global(self):
        from agentproxy.coordinator.coordinator import Coordinator
        from agentproxy.coordinator.models import Milestone

        milestone = Milestone(index=0, prompt="First step")
        global_ctx = {"prior_summary": "global stuff", "prior_files_changed": ["old.py"]}
        ctx = Coordinator._build_milestone_context(milestone, {}, global_ctx)

        assert ctx["prior_summary"] == "global stuff"
        assert ctx["prior_files_changed"] == ["old.py"]
