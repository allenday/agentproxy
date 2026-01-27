"""
Tests for sf.shopfloor package
================================

Tests for WorkOrder models, routing (parse + build_layers),
AssemblyStation, and ShopFloor orchestration.
"""

import os
import subprocess

import pytest

from sf.shopfloor.models import WorkOrder, WorkOrderResult, WorkOrderStatus
from sf.shopfloor.routing import build_layers, match_capabilities, parse_work_orders
from sf.shopfloor.assembly import AssemblyStation, IntegrationResult, IntegrationStatus


# ===========================================================================
# WorkOrder Models
# ===========================================================================


class TestWorkOrderModels:

    def test_work_order_defaults(self):
        wo = WorkOrder(index=0, prompt="Do something")
        assert wo.status == WorkOrderStatus.PENDING
        assert wo.depends_on == []
        assert wo.source == "decomposition"

    def test_work_order_serialize_roundtrip(self):
        wo = WorkOrder(
            index=2,
            prompt="Build feature X",
            depends_on=[0, 1],
            required_capabilities={"gpu": True},
            source="jira",
            source_ref="PROJ-123",
        )
        data = wo.serialize()
        restored = WorkOrder.deserialize(data)
        assert restored.index == 2
        assert restored.prompt == "Build feature X"
        assert restored.depends_on == [0, 1]
        assert restored.required_capabilities == {"gpu": True}
        assert restored.source == "jira"
        assert restored.source_ref == "PROJ-123"

    def test_work_order_result_serialize_roundtrip(self):
        result = WorkOrderResult(
            status="completed",
            events=[{"type": "text", "content": "done"}],
            files_changed=["app.py"],
            summary="WO-0 completed",
            duration=12.5,
            work_order_index=0,
            capabilities_used={"model": "claude-opus"},
        )
        data = result.serialize()
        restored = WorkOrderResult.deserialize(data)
        assert restored.status == "completed"
        assert restored.files_changed == ["app.py"]
        assert restored.duration == 12.5
        assert restored.capabilities_used == {"model": "claude-opus"}


# ===========================================================================
# Routing: parse_work_orders
# ===========================================================================


class TestParseWorkOrders:

    def test_numbered_steps_with_depends(self):
        text = """1. Set up project structure
2. Implement data model (depends: 1)
3. Build API endpoints (depends: 1)
4. Add tests (depends: 2, 3)"""
        wos = parse_work_orders(text)
        assert len(wos) == 4
        assert wos[0].depends_on == []
        assert wos[1].depends_on == [0]  # depends: 1 → index 0
        assert wos[2].depends_on == [0]
        assert wos[3].depends_on == [1, 2]

    def test_bullet_steps_with_depends(self):
        text = """- Set up project structure
- Implement data model (depends: 1)
- Build API endpoints (depends: 1)
- Add tests (depends: 2, 3)"""
        wos = parse_work_orders(text)
        assert len(wos) == 4
        assert wos[0].depends_on == []
        assert wos[1].depends_on == [0]

    def test_no_deps_creates_sequential_chain(self):
        text = """1. First step
2. Second step
3. Third step"""
        wos = parse_work_orders(text)
        assert len(wos) == 3
        # Without dep annotations, creates sequential chain
        assert wos[0].depends_on == []
        assert wos[1].depends_on == [0]
        assert wos[2].depends_on == [1]

    def test_empty_text(self):
        assert parse_work_orders("") == []

    def test_single_step(self):
        text = "1. Do everything"
        wos = parse_work_orders(text)
        assert len(wos) == 1
        assert wos[0].prompt == "Do everything"

    def test_strips_dep_annotation_from_prompt(self):
        text = "1. Build feature X (depends: 1)"
        wos = parse_work_orders(text)
        assert "(depends" not in wos[0].prompt


# ===========================================================================
# Routing: build_layers
# ===========================================================================


class TestBuildLayers:

    def test_all_independent(self):
        """No dependencies → single layer with all work orders."""
        wos = [
            WorkOrder(index=0, prompt="A"),
            WorkOrder(index=1, prompt="B"),
            WorkOrder(index=2, prompt="C"),
        ]
        layers = build_layers(wos)
        assert len(layers) == 1
        assert len(layers[0]) == 3

    def test_sequential_chain(self):
        """Linear dependency → one layer per work order."""
        wos = [
            WorkOrder(index=0, prompt="A"),
            WorkOrder(index=1, prompt="B", depends_on=[0]),
            WorkOrder(index=2, prompt="C", depends_on=[1]),
        ]
        layers = build_layers(wos)
        assert len(layers) == 3
        assert layers[0][0].index == 0
        assert layers[1][0].index == 1
        assert layers[2][0].index == 2

    def test_diamond_dependency(self):
        """Diamond: A → (B, C) → D."""
        wos = [
            WorkOrder(index=0, prompt="A"),
            WorkOrder(index=1, prompt="B", depends_on=[0]),
            WorkOrder(index=2, prompt="C", depends_on=[0]),
            WorkOrder(index=3, prompt="D", depends_on=[1, 2]),
        ]
        layers = build_layers(wos)
        assert len(layers) == 3

        # Layer 0: A
        assert [wo.index for wo in layers[0]] == [0]
        # Layer 1: B and C (parallel)
        assert sorted(wo.index for wo in layers[1]) == [1, 2]
        # Layer 2: D
        assert [wo.index for wo in layers[2]] == [3]

    def test_cycle_breaks_on_lowest_index(self):
        """Cycle detection: breaks by releasing lowest index."""
        wos = [
            WorkOrder(index=0, prompt="A", depends_on=[1]),
            WorkOrder(index=1, prompt="B", depends_on=[0]),
        ]
        layers = build_layers(wos)
        # Should break cycle by releasing index 0 first
        assert len(layers) == 2
        assert layers[0][0].index == 0
        assert layers[1][0].index == 1

    def test_empty(self):
        assert build_layers([]) == []


# ===========================================================================
# AssemblyStation
# ===========================================================================


class TestAssemblyStation:

    def _make_repo(self, tmp_path, name="repo"):
        """Create a git repo fixture and commission it."""
        from sf.workstation import Workstation, GitRepoFixture
        path = str(tmp_path / name)
        fixture = GitRepoFixture(path=path)
        station = Workstation(fixture=fixture)
        station.commission()
        return station

    def test_integrate_clean_merge(self, tmp_path):
        parent = self._make_repo(tmp_path, "parent")

        # Create a child worktree
        child = parent.spawn("child")
        child.commission()

        # Write a file in child
        with open(os.path.join(child.path, "feature.txt"), "w") as f:
            f.write("new feature")
        child.checkpoint("add feature")

        # Integrate
        assembly = AssemblyStation()
        result = assembly.integrate(parent, child)

        assert result.status == IntegrationStatus.SUCCESS
        assert "feature.txt" in result.merged_files

        # Verify file now exists in parent
        assert os.path.exists(os.path.join(parent.path, "feature.txt"))

        child.decommission()

    def test_integrate_conflict(self, tmp_path):
        parent = self._make_repo(tmp_path, "parent")

        # Write a file in parent
        with open(os.path.join(parent.path, "shared.txt"), "w") as f:
            f.write("parent content")
        parent.checkpoint("parent version")

        # Fork child from updated parent
        child = parent.spawn("conflict-child")
        child.commission()

        # Modify same file differently in child
        with open(os.path.join(child.path, "shared.txt"), "w") as f:
            f.write("child content (conflicting)")
        child.checkpoint("child version")

        # Also modify in parent after fork
        with open(os.path.join(parent.path, "shared.txt"), "w") as f:
            f.write("parent content (conflicting)")
        parent.checkpoint("parent conflicting version")

        # Integrate — should detect conflict
        assembly = AssemblyStation()
        result = assembly.integrate(parent, child)

        assert result.status == IntegrationStatus.CONFLICT
        assert len(result.conflicted_files) > 0

        child.decommission()

    def test_conflict_leaves_parent_clean(self, tmp_path):
        parent = self._make_repo(tmp_path, "parent")

        with open(os.path.join(parent.path, "shared.txt"), "w") as f:
            f.write("original")
        parent.checkpoint("original")

        child = parent.spawn("conflict-clean")
        child.commission()

        with open(os.path.join(child.path, "shared.txt"), "w") as f:
            f.write("child version")
        child.checkpoint("child changes")

        with open(os.path.join(parent.path, "shared.txt"), "w") as f:
            f.write("parent version")
        parent.checkpoint("parent changes")

        assembly = AssemblyStation()
        result = assembly.integrate(parent, child)

        if result.status == IntegrationStatus.CONFLICT:
            # Parent should be clean (merge aborted)
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=parent.path,
                capture_output=True,
                text=True,
            )
            assert status_result.stdout.strip() == ""

        child.decommission()


# ===========================================================================
# ShopFloor
# ===========================================================================


class TestShopFloor:

    def test_import(self):
        from sf.shopfloor import ShopFloor
        assert ShopFloor is not None

    def test_shopfloor_init(self):
        """ShopFloor can be initialized with a mock PA."""
        from sf.shopfloor import ShopFloor

        class MockPA:
            pass

        sf = ShopFloor(pa=MockPA())
        assert sf.pa is not None
        assert sf.queue == "default"
        assert sf.assembly is not None

    def test_routing_roundtrip(self):
        """Verify parse → build_layers produces correct topology."""
        text = """1. Setup project
2. Build frontend (depends: 1)
3. Build backend (depends: 1)
4. Integration tests (depends: 2, 3)"""

        wos = parse_work_orders(text)
        layers = build_layers(wos)

        assert len(layers) == 3
        # Layer 0: Setup
        assert len(layers[0]) == 1
        # Layer 1: Frontend + Backend (parallel)
        assert len(layers[1]) == 2
        # Layer 2: Integration tests
        assert len(layers[2]) == 1


# ===========================================================================
# Match Capabilities
# ===========================================================================


class TestMatchCapabilities:

    def test_exact_match(self):
        assert match_capabilities({"gpu": True}, {"gpu": True})

    def test_min_threshold(self):
        assert match_capabilities(
            {"context_window": {"min": 200000}},
            {"context_window": 1000000},
        )

    def test_missing_capability_fails(self):
        assert not match_capabilities({"gpu": True}, {})

    def test_superset_passes(self):
        assert match_capabilities(
            {"gpu": True},
            {"gpu": True, "disk_gb": 500},
        )

    def test_multiple_requirements(self):
        assert match_capabilities(
            {"gpu": True, "context_window": {"min": 100000}},
            {"gpu": True, "context_window": 200000, "disk_gb": 500},
        )

    def test_partial_match_fails(self):
        assert not match_capabilities(
            {"gpu": True, "tpu": True},
            {"gpu": True},
        )
