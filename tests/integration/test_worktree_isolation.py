"""
Integration Tests: Worktree Isolation
======================================

Real git worktree fork/merge tests. These test actual git operations
to verify that parallel workstations are truly isolated and can
be merged back correctly.
"""

import os
import subprocess

import pytest

from sf.workstation import Workstation, GitRepoFixture, GitWorktreeFixture
from sf.shopfloor.assembly import AssemblyStation, IntegrationStatus


class TestParallelWorktreeIsolation:
    """Verify that parallel worktrees are truly isolated."""

    def _make_repo(self, tmp_path, name="repo"):
        """Create and commission a git repo workstation."""
        path = str(tmp_path / name)
        fixture = GitRepoFixture(path=path)
        station = Workstation(fixture=fixture)
        station.commission()
        return station

    def test_parallel_worktrees_are_isolated(self, tmp_path):
        """Write different files in two worktrees — no cross-contamination."""
        parent = self._make_repo(tmp_path)

        # Spawn two children
        child_a = parent.spawn("worker-a")
        child_b = parent.spawn("worker-b")
        child_a.commission()
        child_b.commission()

        # Write different files in each
        with open(os.path.join(child_a.path, "feature_a.txt"), "w") as f:
            f.write("Feature A implementation")

        with open(os.path.join(child_b.path, "feature_b.txt"), "w") as f:
            f.write("Feature B implementation")

        # Verify isolation: each child's file should not appear in the other
        assert os.path.exists(os.path.join(child_a.path, "feature_a.txt"))
        assert not os.path.exists(os.path.join(child_a.path, "feature_b.txt"))

        assert os.path.exists(os.path.join(child_b.path, "feature_b.txt"))
        assert not os.path.exists(os.path.join(child_b.path, "feature_a.txt"))

        # Neither should appear in parent yet
        assert not os.path.exists(os.path.join(parent.path, "feature_a.txt"))
        assert not os.path.exists(os.path.join(parent.path, "feature_b.txt"))

        child_a.decommission()
        child_b.decommission()

    def test_merge_after_parallel_work(self, tmp_path):
        """Fork, write in children, checkpoint, integrate, verify both files in parent."""
        parent = self._make_repo(tmp_path)
        assembly = AssemblyStation()

        # Checkpoint parent to have a clean state
        parent.checkpoint("pre-parallel")

        # Spawn children
        child_a = parent.spawn("merge-a")
        child_b = parent.spawn("merge-b")
        child_a.commission()
        child_b.commission()

        # Write and checkpoint in each child
        with open(os.path.join(child_a.path, "file_a.py"), "w") as f:
            f.write("def feature_a():\n    return 'A'\n")
        child_a.checkpoint("WO-0: feature A")

        with open(os.path.join(child_b.path, "file_b.py"), "w") as f:
            f.write("def feature_b():\n    return 'B'\n")
        child_b.checkpoint("WO-1: feature B")

        # Integrate child_a into parent
        result_a = assembly.integrate(parent, child_a)
        assert result_a.status == IntegrationStatus.SUCCESS
        assert "file_a.py" in result_a.merged_files

        # Integrate child_b into parent
        result_b = assembly.integrate(parent, child_b)
        assert result_b.status == IntegrationStatus.SUCCESS
        assert "file_b.py" in result_b.merged_files

        # Verify both files now exist in parent
        assert os.path.exists(os.path.join(parent.path, "file_a.py"))
        assert os.path.exists(os.path.join(parent.path, "file_b.py"))

        # Verify content
        with open(os.path.join(parent.path, "file_a.py")) as f:
            assert "feature_a" in f.read()
        with open(os.path.join(parent.path, "file_b.py")) as f:
            assert "feature_b" in f.read()

        child_a.decommission()
        child_b.decommission()

    def test_merge_conflict_detected(self, tmp_path):
        """Same file, different content → CONFLICT status."""
        parent = self._make_repo(tmp_path)
        assembly = AssemblyStation()

        # Write initial file and checkpoint
        with open(os.path.join(parent.path, "config.py"), "w") as f:
            f.write("# Config\nDEBUG = False\n")
        parent.checkpoint("initial config")

        # Spawn two children that modify the same file
        child_a = parent.spawn("conflict-a")
        child_b = parent.spawn("conflict-b")
        child_a.commission()
        child_b.commission()

        # Both modify config.py differently
        with open(os.path.join(child_a.path, "config.py"), "w") as f:
            f.write("# Config\nDEBUG = True  # Enabled for dev\n")
        child_a.checkpoint("enable debug")

        with open(os.path.join(child_b.path, "config.py"), "w") as f:
            f.write("# Config\nDEBUG = False  # Disabled for prod\nLOG_LEVEL = 'INFO'\n")
        child_b.checkpoint("add logging config")

        # Integrate child_a first (should succeed)
        result_a = assembly.integrate(parent, child_a)
        assert result_a.status == IntegrationStatus.SUCCESS

        # Integrate child_b should conflict (both modified config.py)
        result_b = assembly.integrate(parent, child_b)
        assert result_b.status == IntegrationStatus.CONFLICT
        assert "config.py" in result_b.conflicted_files

        # Parent should be clean after conflict (merge aborted)
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=parent.path,
            capture_output=True,
            text=True,
        )
        assert status.stdout.strip() == ""

        child_a.decommission()
        child_b.decommission()

    def test_three_parallel_workers_all_merge(self, tmp_path):
        """Three workers on different files all merge cleanly."""
        parent = self._make_repo(tmp_path)
        assembly = AssemblyStation()

        # Spawn three children
        children = []
        for i in range(3):
            child = parent.spawn(f"worker-{i}")
            child.commission()
            children.append(child)

        # Each writes a different file
        for i, child in enumerate(children):
            filename = f"module_{i}.py"
            with open(os.path.join(child.path, filename), "w") as f:
                f.write(f"def func_{i}():\n    return {i}\n")
            child.checkpoint(f"WO-{i}: module {i}")

        # Integrate all
        for i, child in enumerate(children):
            result = assembly.integrate(parent, child)
            assert result.status == IntegrationStatus.SUCCESS, \
                f"Failed to merge worker-{i}: {result.message}"

        # Verify all files exist in parent
        for i in range(3):
            filepath = os.path.join(parent.path, f"module_{i}.py")
            assert os.path.exists(filepath), f"module_{i}.py missing from parent"

        # Cleanup
        for child in children:
            child.decommission()

    def test_worktree_paths_are_distinct(self, tmp_path):
        """Each spawned worktree gets a unique path."""
        parent = self._make_repo(tmp_path)

        child_a = parent.spawn("alpha")
        child_b = parent.spawn("beta")
        child_a.commission()
        child_b.commission()

        assert child_a.path != child_b.path
        assert child_a.path != parent.path
        assert child_b.path != parent.path

        child_a.decommission()
        child_b.decommission()

    def test_child_inherits_parent_files(self, tmp_path):
        """A forked worktree starts with the parent's committed files."""
        parent = self._make_repo(tmp_path)

        # Write and commit a file in parent
        with open(os.path.join(parent.path, "base.txt"), "w") as f:
            f.write("base content")
        parent.checkpoint("add base")

        # Fork
        child = parent.spawn("inherits")
        child.commission()

        # Child should have the file
        assert os.path.exists(os.path.join(child.path, "base.txt"))
        with open(os.path.join(child.path, "base.txt")) as f:
            assert f.read() == "base content"

        child.decommission()
