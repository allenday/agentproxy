"""
GitWorktreeFixture
==================

Local parallelism via `git worktree add`. Created by GitRepoFixture.fork().

- setup(): `git worktree add -b <branch> <path>`
- teardown(): `git worktree remove` + delete branch
- fork(): nested worktree (same object store)
- checkpoint(): commit in worktree
"""

import os
import subprocess
from typing import Any, Dict, Optional

from .base import Fixture
from .gitignore import ensure_gitignore


class GitWorktreeFixture(Fixture):
    """Git worktree fixture for local parallel isolation.

    Created by GitRepoFixture.fork(). Each worktree gets its own
    branch and working directory, sharing the same object store
    (near-instant SMED changeover).
    """

    def __init__(self, parent_path: str, worktree_path: str, branch: str):
        self._parent_path = os.path.abspath(parent_path)
        self._worktree_path = os.path.abspath(worktree_path)
        self._branch = branch

    def setup(self) -> str:
        """Create the worktree. Idempotent.

        Returns:
            Absolute path to the worktree directory.
        """
        if os.path.isdir(self._worktree_path):
            ensure_gitignore(
                self._worktree_path,
                [
                    ".claude/",
                    "CLAUDE.md",
                ],
            )
            return self._worktree_path

        # Create worktree with new branch from HEAD of parent
        self._parent_git(
            "worktree", "add", "-b", self._branch,
            self._worktree_path, "HEAD",
        )
        ensure_gitignore(
            self._worktree_path,
            [
                ".claude/",
                "CLAUDE.md",
            ],
        )
        return self._worktree_path

    def teardown(self) -> None:
        """Remove the worktree and delete its branch."""
        try:
            self._parent_git("worktree", "remove", self._worktree_path, "--force")
        except subprocess.CalledProcessError:
            # Worktree may already be removed
            pass

        # Clean up the branch
        try:
            self._parent_git("branch", "-D", self._branch)
        except subprocess.CalledProcessError:
            pass

        # Prune stale worktrees
        try:
            self._parent_git("worktree", "prune")
        except subprocess.CalledProcessError:
            pass

    def fork(self, name: str) -> "Fixture":
        """Create a nested worktree from this worktree.

        Uses the same parent repo's object store.
        Branch naming uses '-' separator to avoid git ref path conflicts
        (git cannot have both refs/heads/sf/X and refs/heads/sf/X/Y).
        """
        branch_name = f"{self._branch}-{name}"
        nested_path = os.path.join(
            os.path.dirname(self._worktree_path),
            f".sf-worktree-{name}",
        )
        return GitWorktreeFixture(
            parent_path=self._parent_path,
            worktree_path=nested_path,
            branch=branch_name,
        )

    def checkpoint(self, message: str) -> Optional[str]:
        """Commit all changes in the worktree. Returns commit hash or None."""
        try:
            self._git("add", "-A")

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
        return self._worktree_path

    @property
    def branch(self) -> str:
        return self._branch

    @property
    def parent_path(self) -> str:
        return self._parent_path

    def serialize(self) -> Dict[str, Any]:
        return {
            "type": "git_worktree",
            "parent_path": self._parent_path,
            "worktree_path": self._worktree_path,
            "branch": self._branch,
        }

    @staticmethod
    def _from_dict(data: Dict[str, Any]) -> "GitWorktreeFixture":
        return GitWorktreeFixture(
            parent_path=data["parent_path"],
            worktree_path=data["worktree_path"],
            branch=data["branch"],
        )

    # --- Internal helpers ---

    def _git(self, *args: str) -> str:
        """Run a git command in the worktree directory."""
        result = subprocess.run(
            ["git"] + list(args),
            cwd=self._worktree_path,
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

    def _parent_git(self, *args: str) -> str:
        """Run a git command in the parent repo directory."""
        result = subprocess.run(
            ["git"] + list(args),
            cwd=self._parent_path,
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
