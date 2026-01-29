"""
Tests for sf.workstation package
=================================

Tests for Workstation, Fixtures (LocalDir, GitRepo, GitWorktree, GitClone),
WorkstationHook, QualityGate, and capability matching.
"""

import os
import subprocess
import tempfile

import pytest

from sf.workstation import (
    Workstation,
    WorkstationState,
    WorkstationHook,
    Fixture,
    LocalDirFixture,
    GitRepoFixture,
    GitWorktreeFixture,
    GitCloneFixture,
    QualityGate,
    VerificationGate,
    HumanApprovalGate,
    InspectionResult,
    create_workstation,
)


# ===========================================================================
# LocalDirFixture
# ===========================================================================


class TestLocalDirFixture:

    def test_setup_creates_directory(self, tmp_path):
        path = str(tmp_path / "new_dir")
        fixture = LocalDirFixture(path=path)
        result = fixture.setup()
        assert os.path.isdir(path)
        assert result == os.path.abspath(path)

    def test_setup_idempotent(self, tmp_path):
        path = str(tmp_path / "dir")
        fixture = LocalDirFixture(path=path)
        fixture.setup()
        fixture.setup()  # Should not raise
        assert os.path.isdir(path)

    def test_teardown_preserves_dir(self, tmp_path):
        path = str(tmp_path / "dir")
        fixture = LocalDirFixture(path=path)
        fixture.setup()
        fixture.teardown()
        assert os.path.isdir(path)

    def test_fork_raises_not_implemented(self, tmp_path):
        fixture = LocalDirFixture(path=str(tmp_path))
        with pytest.raises(NotImplementedError):
            fixture.fork("child")

    def test_checkpoint_noop(self, tmp_path):
        fixture = LocalDirFixture(path=str(tmp_path))
        fixture.setup()
        result = fixture.checkpoint("test")
        assert result is None

    def test_path_property(self, tmp_path):
        fixture = LocalDirFixture(path=str(tmp_path))
        assert fixture.path == os.path.abspath(str(tmp_path))

    def test_serialize_roundtrip(self, tmp_path):
        fixture = LocalDirFixture(path=str(tmp_path))
        data = fixture.serialize()
        assert data["type"] == "local_dir"
        restored = Fixture.deserialize(data)
        assert isinstance(restored, LocalDirFixture)
        assert restored.path == fixture.path


# ===========================================================================
# GitRepoFixture
# ===========================================================================


class TestGitRepoFixture:

    def test_setup_inits_repo(self, tmp_path):
        path = str(tmp_path / "repo")
        fixture = GitRepoFixture(path=path)
        result = fixture.setup()
        assert os.path.isdir(os.path.join(path, ".git"))
        assert result == os.path.abspath(path)

    def test_setup_existing_repo(self, tmp_path):
        """Setup on an existing git repo should not re-init."""
        path = str(tmp_path / "repo")
        os.makedirs(path)
        subprocess.run(["git", "init"], cwd=path, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                        cwd=path, capture_output=True)
        fixture = GitRepoFixture(path=path)
        fixture.setup()  # Should not raise
        assert os.path.isdir(os.path.join(path, ".git"))

    def test_setup_idempotent(self, tmp_path):
        path = str(tmp_path / "repo")
        fixture = GitRepoFixture(path=path)
        fixture.setup()
        fixture.setup()  # Second call is idempotent
        assert os.path.isdir(os.path.join(path, ".git"))

    def test_checkpoint_commits(self, tmp_path):
        path = str(tmp_path / "repo")
        fixture = GitRepoFixture(path=path)
        fixture.setup()

        # Create a file
        with open(os.path.join(path, "test.txt"), "w") as f:
            f.write("hello")

        commit_hash = fixture.checkpoint("test commit")
        assert commit_hash is not None
        assert len(commit_hash) == 40  # Full SHA

    def test_checkpoint_nothing_to_commit(self, tmp_path):
        path = str(tmp_path / "repo")
        fixture = GitRepoFixture(path=path)
        fixture.setup()
        # No changes — should return None
        result = fixture.checkpoint("empty")
        assert result is None

    def test_fork_creates_worktree(self, tmp_path):
        path = str(tmp_path / "repo")
        fixture = GitRepoFixture(path=path)
        fixture.setup()

        child = fixture.fork("child-1")
        assert isinstance(child, GitWorktreeFixture)
        child.setup()
        assert os.path.isdir(child.path)

        # Cleanup
        child.teardown()

    def test_fork_branch_naming(self, tmp_path):
        path = str(tmp_path / "repo")
        fixture = GitRepoFixture(path=path)
        fixture.setup()

        child = fixture.fork("wo-5")
        assert isinstance(child, GitWorktreeFixture)
        assert child.branch == "sf/wo-5"

    def test_teardown_prunes_worktrees(self, tmp_path):
        path = str(tmp_path / "repo")
        fixture = GitRepoFixture(path=path)
        fixture.setup()
        fixture.teardown()  # Should not raise even with no worktrees

    def test_serialize_roundtrip(self, tmp_path):
        path = str(tmp_path / "repo")
        fixture = GitRepoFixture(path=path)
        fixture.setup()
        data = fixture.serialize()
        assert data["type"] == "git_repo"
        restored = Fixture.deserialize(data)
        assert isinstance(restored, GitRepoFixture)
        assert restored.path == fixture.path

    def test_branch_property(self, tmp_path):
        path = str(tmp_path / "repo")
        fixture = GitRepoFixture(path=path)
        fixture.setup()
        # Branch should be detected after setup
        assert fixture.branch != ""


# ===========================================================================
# GitWorktreeFixture
# ===========================================================================


class TestGitWorktreeFixture:

    def _make_repo(self, tmp_path):
        """Helper: create a git repo with an initial commit."""
        path = str(tmp_path / "repo")
        fixture = GitRepoFixture(path=path)
        fixture.setup()
        return fixture

    def test_setup_creates_worktree(self, tmp_path):
        repo = self._make_repo(tmp_path)
        child = repo.fork("test")
        child.setup()
        assert os.path.isdir(child.path)

    def test_worktree_is_isolated(self, tmp_path):
        repo = self._make_repo(tmp_path)

        # Create file in parent
        with open(os.path.join(repo.path, "parent.txt"), "w") as f:
            f.write("parent")
        repo.checkpoint("parent file")

        # Fork creates worktree from HEAD (before parent.txt was committed,
        # but checkpoint makes it available to HEAD)
        child = repo.fork("isolated")
        child.setup()

        # Create file in child
        with open(os.path.join(child.path, "child.txt"), "w") as f:
            f.write("child")

        # Child file should not appear in parent
        assert not os.path.exists(os.path.join(repo.path, "child.txt"))
        # Parent committed file should be in child (from HEAD)
        assert os.path.exists(os.path.join(child.path, "parent.txt"))

        child.teardown()

    def test_checkpoint_in_worktree(self, tmp_path):
        repo = self._make_repo(tmp_path)
        child = repo.fork("ckpt")
        child.setup()

        with open(os.path.join(child.path, "work.txt"), "w") as f:
            f.write("work output")

        commit = child.checkpoint("checkpoint test")
        assert commit is not None
        assert len(commit) == 40

        child.teardown()

    def test_teardown_removes_worktree_and_branch(self, tmp_path):
        repo = self._make_repo(tmp_path)
        child = repo.fork("remove-me")
        child.setup()
        worktree_path = child.path
        branch = child.branch

        child.teardown()

        assert not os.path.isdir(worktree_path)

        # Branch should be deleted
        result = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=repo.path,
            capture_output=True,
            text=True,
        )
        assert branch not in result.stdout

    def test_nested_fork(self, tmp_path):
        repo = self._make_repo(tmp_path)
        child = repo.fork("level1")
        child.setup()

        nested = child.fork("level2")
        assert isinstance(nested, GitWorktreeFixture)
        assert nested.branch == "sf/level1-level2"

        nested.setup()
        assert os.path.isdir(nested.path)

        nested.teardown()
        child.teardown()

    def test_serialize_roundtrip(self, tmp_path):
        repo = self._make_repo(tmp_path)
        child = repo.fork("serial")
        data = child.serialize()
        assert data["type"] == "git_worktree"
        restored = Fixture.deserialize(data)
        assert isinstance(restored, GitWorktreeFixture)
        assert restored.path == child.path


# ===========================================================================
# GitCloneFixture
# ===========================================================================


class TestGitCloneFixture:

    def _make_bare_repo(self, tmp_path):
        """Create a bare git repo to serve as origin."""
        bare_path = str(tmp_path / "origin.git")
        subprocess.run(["git", "init", "--bare", bare_path],
                        capture_output=True, check=True)

        # Create a working repo, make initial commit, push to bare
        work_path = str(tmp_path / "work")
        subprocess.run(["git", "clone", bare_path, work_path],
                        capture_output=True, check=True)
        open(os.path.join(work_path, "README"), "w").close()
        subprocess.run(["git", "add", "README"], cwd=work_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=work_path, capture_output=True)
        subprocess.run(["git", "push"], cwd=work_path, capture_output=True)

        return bare_path

    def test_setup_clones_repo(self, tmp_path):
        bare = self._make_bare_repo(tmp_path)
        clone_path = str(tmp_path / "clone")
        fixture = GitCloneFixture(repo_url=bare, clone_path=clone_path)
        result = fixture.setup()
        assert os.path.isdir(clone_path)
        assert os.path.isdir(os.path.join(clone_path, ".git"))
        assert result == os.path.abspath(clone_path)

    def test_setup_creates_branch(self, tmp_path):
        bare = self._make_bare_repo(tmp_path)
        clone_path = str(tmp_path / "clone")
        fixture = GitCloneFixture(repo_url=bare, clone_path=clone_path, branch="sf/test")
        fixture.setup()

        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=clone_path, capture_output=True, text=True,
        )
        assert result.stdout.strip() == "sf/test"

    def test_checkpoint_and_push(self, tmp_path):
        bare = self._make_bare_repo(tmp_path)
        clone_path = str(tmp_path / "clone")
        fixture = GitCloneFixture(repo_url=bare, clone_path=clone_path, branch="sf/work")
        fixture.setup()

        with open(os.path.join(clone_path, "output.txt"), "w") as f:
            f.write("work done")

        commit = fixture.checkpoint("work checkpoint")
        assert commit is not None

    def test_teardown_removes_clone(self, tmp_path):
        bare = self._make_bare_repo(tmp_path)
        clone_path = str(tmp_path / "clone")
        fixture = GitCloneFixture(repo_url=bare, clone_path=clone_path)
        fixture.setup()
        fixture.teardown()
        assert not os.path.isdir(clone_path)

    def test_fork_creates_new_clone(self, tmp_path):
        bare = self._make_bare_repo(tmp_path)
        clone_path = str(tmp_path / "clone")
        fixture = GitCloneFixture(repo_url=bare, clone_path=clone_path, branch="sf/parent")
        child = fixture.fork("child")
        assert isinstance(child, GitCloneFixture)
        assert "child" in child.path
        assert child.branch == "sf/parent/child"

    def test_serialize_roundtrip(self, tmp_path):
        fixture = GitCloneFixture(
            repo_url="https://example.com/repo.git",
            clone_path="/tmp/test-clone",
            branch="sf/test",
        )
        data = fixture.serialize()
        assert data["type"] == "git_clone"
        restored = Fixture.deserialize(data)
        assert isinstance(restored, GitCloneFixture)
        assert restored.repo_url == fixture.repo_url
        assert restored.path == fixture.path


# ===========================================================================
# Workstation
# ===========================================================================


class _TestHook(WorkstationHook):
    """Test hook that records calls."""

    def __init__(self):
        self.calls = []

    def pre_commission(self, station):
        self.calls.append("pre_commission")

    def post_production(self, station):
        self.calls.append("post_production")

    def on_checkpoint(self, station, commit_hash):
        self.calls.append(f"on_checkpoint:{commit_hash[:8]}")


class TestWorkstation:

    def test_commission_calls_fixture_setup(self, tmp_path):
        fixture = LocalDirFixture(path=str(tmp_path / "ws"))
        station = Workstation(fixture=fixture)
        path = station.commission()
        assert os.path.isdir(path)
        assert station.state == WorkstationState.READY

    def test_decommission_calls_teardown(self, tmp_path):
        fixture = LocalDirFixture(path=str(tmp_path / "ws"))
        station = Workstation(fixture=fixture)
        station.commission()
        station.decommission()
        assert station.state == WorkstationState.DECOMMISSIONED

    def test_spawn_creates_child_with_same_capabilities(self, tmp_path):
        path = str(tmp_path / "repo")
        fixture = GitRepoFixture(path=path)
        caps = {"gpu": True, "context_window": 200000}
        station = Workstation(fixture=fixture, capabilities=caps)
        station.commission()

        child = station.spawn("child-1")
        # Capabilities are now typed WorkstationCapabilities, not dicts
        assert child.capabilities.gpu is True
        assert child.capabilities.context_window == 200000
        assert child.capabilities == station.capabilities
        child.commission()
        assert child.state == WorkstationState.READY

        child.decommission()

    def test_hooks_called_on_commission_and_decommission(self, tmp_path):
        fixture = LocalDirFixture(path=str(tmp_path / "ws"))
        hook = _TestHook()
        station = Workstation(fixture=fixture, hooks=[hook])

        station.commission()
        assert "pre_commission" in hook.calls

        station.decommission()
        assert "post_production" in hook.calls

    def test_hooks_called_on_checkpoint(self, tmp_path):
        path = str(tmp_path / "repo")
        fixture = GitRepoFixture(path=path)
        hook = _TestHook()
        station = Workstation(fixture=fixture, hooks=[hook])
        station.commission()

        with open(os.path.join(path, "test.txt"), "w") as f:
            f.write("content")

        commit = station.checkpoint("test checkpoint")
        assert commit is not None
        assert any(c.startswith("on_checkpoint:") for c in hook.calls)

    def test_state_transitions(self, tmp_path):
        fixture = LocalDirFixture(path=str(tmp_path / "ws"))
        station = Workstation(fixture=fixture)

        assert station.state == WorkstationState.IDLE
        station.commission()
        assert station.state == WorkstationState.READY
        station.decommission()
        assert station.state == WorkstationState.DECOMMISSIONED

    def test_serialize_roundtrip(self, tmp_path):
        path = str(tmp_path / "repo")
        fixture = GitRepoFixture(path=path)
        caps = {"gpu": True}
        station = Workstation(fixture=fixture, capabilities=caps)
        station.commission()

        data = station.serialize()
        assert "fixture" in data
        # Capabilities are now fully typed; check the key field
        assert data["capabilities"]["gpu"] is True

        restored = Workstation.deserialize(data)
        assert restored.path == station.path
        assert restored.capabilities == station.capabilities

    def test_path_property(self, tmp_path):
        fixture = LocalDirFixture(path=str(tmp_path / "ws"))
        station = Workstation(fixture=fixture)
        assert station.path == fixture.path


# ===========================================================================
# QualityGate
# ===========================================================================


class TestVerificationGate:

    def _make_station_with_sop(self, tmp_path, verification_commands):
        """Create a workstation with an SOP that has verification_commands."""
        from sf.workstation.sop import SOP
        fixture = LocalDirFixture(path=str(tmp_path))
        station = Workstation(fixture=fixture)
        station.commission()
        station.sop = SOP(name="test", claude_md="", verification_commands=verification_commands)
        return station

    def test_passing_command(self, tmp_path):
        station = self._make_station_with_sop(tmp_path, ["true"])
        gate = VerificationGate()
        result = gate.inspect(None, None, station)
        assert result.passed is True
        assert len(result.defects) == 0

    def test_failing_command(self, tmp_path):
        station = self._make_station_with_sop(tmp_path, ["false"])
        gate = VerificationGate()
        result = gate.inspect(None, None, station)
        assert result.passed is False
        assert len(result.defects) == 1

    def test_multiple_commands_one_fails(self, tmp_path):
        station = self._make_station_with_sop(tmp_path, ["true", "false", "true"])
        gate = VerificationGate()
        result = gate.inspect(None, None, station)
        assert result.passed is False
        assert len(result.defects) == 1  # Only 'false' fails

    def test_no_sop_skips_verification(self, tmp_path):
        fixture = LocalDirFixture(path=str(tmp_path))
        station = Workstation(fixture=fixture)
        station.commission()
        gate = VerificationGate()
        result = gate.inspect(None, None, station)
        assert result.passed is True
        assert "No verification commands" in result.details


class TestHumanApprovalGate:

    def test_auto_approve(self, tmp_path):
        fixture = LocalDirFixture(path=str(tmp_path))
        station = Workstation(fixture=fixture)
        station.commission()

        gate = HumanApprovalGate(auto_policy="approve")
        result = gate.inspect(None, None, station)
        assert result.passed is True

    def test_auto_reject(self, tmp_path):
        fixture = LocalDirFixture(path=str(tmp_path))
        station = Workstation(fixture=fixture)
        station.commission()

        gate = HumanApprovalGate(auto_policy="reject")
        result = gate.inspect(None, None, station)
        assert result.passed is False


# ===========================================================================
# Capability Matching (from routing)
# ===========================================================================


class TestCapabilityMatching:

    def test_exact_match(self):
        from sf.shopfloor.routing import match_capabilities
        assert match_capabilities({"gpu": True}, {"gpu": True}) is True

    def test_exact_mismatch(self):
        from sf.shopfloor.routing import match_capabilities
        assert match_capabilities({"gpu": True}, {"gpu": False}) is False

    def test_min_threshold_passes(self):
        from sf.shopfloor.routing import match_capabilities
        assert match_capabilities(
            {"context_window": {"min": 200000}},
            {"context_window": 1000000},
        ) is True

    def test_min_threshold_fails(self):
        from sf.shopfloor.routing import match_capabilities
        assert match_capabilities(
            {"context_window": {"min": 200000}},
            {"context_window": 100000},
        ) is False

    def test_missing_capability_fails(self):
        from sf.shopfloor.routing import match_capabilities
        assert match_capabilities({"gpu": True}, {}) is False

    def test_superset_passes(self):
        from sf.shopfloor.routing import match_capabilities
        assert match_capabilities(
            {"gpu": True},
            {"gpu": True, "disk_gb": 500, "network": "fast"},
        ) is True

    def test_empty_requirements(self):
        from sf.shopfloor.routing import match_capabilities
        assert match_capabilities({}, {"gpu": True}) is True


# ===========================================================================
# create_workstation factory
# ===========================================================================


class TestCreateWorkstation:

    def test_auto_detects_local(self, tmp_path):
        path = str(tmp_path / "local")
        os.makedirs(path)
        station = create_workstation(path)
        assert isinstance(station.fixture, LocalDirFixture)

    def test_auto_detects_git(self, tmp_path):
        path = str(tmp_path / "repo")
        os.makedirs(path)
        subprocess.run(["git", "init"], cwd=path, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                        cwd=path, capture_output=True)
        station = create_workstation(path)
        assert isinstance(station.fixture, GitRepoFixture)

    def test_explicit_local(self, tmp_path):
        path = str(tmp_path / "local")
        os.makedirs(path)
        station = create_workstation(path, context_type="local")
        assert isinstance(station.fixture, LocalDirFixture)

    def test_explicit_git(self, tmp_path):
        path = str(tmp_path / "repo")
        station = create_workstation(path, context_type="git")
        assert isinstance(station.fixture, GitRepoFixture)
