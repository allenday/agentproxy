"""
GitRepoFixture
==============

Primary fixture: a git repository. Replaces PA._ensure_git_repo().

- setup(): initializes git repo if needed, creates baseline commit.
- teardown(): prunes worktrees (does not delete the repo).
- fork(): creates a GitWorktreeFixture via `git worktree add`.
- checkpoint(): commits all changes with the given message.
"""

import os
import subprocess
from typing import Any, Dict, Optional

from .base import Fixture


class GitRepoFixture(Fixture):
    """Git repository fixture for the primary working directory.

    Manages git init, baseline commits, worktree forking, and checkpoints.
    """

    def __init__(self, path: str, branch: str = ""):
        self._path = os.path.abspath(path)
        self._branch = branch  # empty means default/current branch

    def setup(self) -> str:
        """Initialize git repo if needed, create baseline commit. Idempotent.

        Returns:
            Absolute path to the working directory.
        """
        os.makedirs(self._path, exist_ok=True)

        if not self._is_git_repo():
            self._git("init")
            # Create baseline commit for reliable diff tracking
            self._git("add", "-A")
            self._git("commit", "--allow-empty", "-m", "baseline: initial commit")

        # Ensure we have at least one commit (existing repo with no commits)
        try:
            self._git("rev-parse", "HEAD")
        except subprocess.CalledProcessError:
            self._git("add", "-A")
            self._git("commit", "--allow-empty", "-m", "baseline: initial commit")

        # Record branch name
        if not self._branch:
            try:
                result = self._git("rev-parse", "--abbrev-ref", "HEAD")
                self._branch = result.strip()
            except subprocess.CalledProcessError:
                self._branch = "main"

        return self._path

    def teardown(self) -> None:
        """Prune stale worktrees. Does not delete the repo."""
        try:
            self._git("worktree", "prune")
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    def fork(self, name: str) -> "Fixture":
        """Create an isolated child via `git worktree add`.

        Args:
            name: Identifier for the worktree branch (e.g., "wo-1").

        Returns:
            GitWorktreeFixture pointing to the new worktree.
        """
        from .git_worktree import GitWorktreeFixture

        branch_name = f"sf/{name}"
        worktree_path = os.path.join(
            os.path.dirname(self._path),
            f".sf-worktree-{name}",
        )
        return GitWorktreeFixture(
            parent_path=self._path,
            worktree_path=worktree_path,
            branch=branch_name,
        )

    def checkpoint(self, message: str) -> Optional[str]:
        """Commit all changes. Returns commit hash or None if nothing to commit."""
        try:
            # Stage everything
            self._git("add", "-A")

            # Check if there's anything to commit
            result = self._git("status", "--porcelain")
            if not result.strip():
                return None

            self._git("commit", "-m", message)
            commit_hash = self._git("rev-parse", "HEAD").strip()
            return commit_hash
        except subprocess.CalledProcessError:
            return None

    @property
    def path(self) -> str:
        return self._path

    @property
    def branch(self) -> str:
        return self._branch

    def serialize(self) -> Dict[str, Any]:
        return {
            "type": "git_repo",
            "path": self._path,
            "branch": self._branch,
        }

    @staticmethod
    def _from_dict(data: Dict[str, Any]) -> "GitRepoFixture":
        return GitRepoFixture(
            path=data["path"],
            branch=data.get("branch", ""),
        )

    # --- Internal helpers ---

    def _is_git_repo(self) -> bool:
        """Check if the working directory is inside a git repository."""
        try:
            self._git("rev-parse", "--git-dir")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _git(self, *args: str) -> str:
        """Run a git command in the working directory. Returns stdout."""
        result = subprocess.run(
            ["git"] + list(args),
            cwd=self._path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                ["git"] + list(args),
                output=result.stdout,
                stderr=result.stderr,
            )
        return result.stdout
