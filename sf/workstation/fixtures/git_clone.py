"""
GitCloneFixture
===============

Distributed parallelism via `git clone`. For remote workers that
cannot share the local filesystem (Celery workers on different machines).

- setup(): clones the repo and creates a working branch.
- teardown(): removes the clone directory.
- fork(): creates another clone with a sub-branch.
- checkpoint(): commits and pushes to origin.
"""

import os
import shutil
import subprocess
from typing import Any, Dict, Optional

from .base import Fixture


class GitCloneFixture(Fixture):
    """Git clone fixture for distributed parallel isolation.

    Used when workers are on different machines and cannot share
    the local filesystem. Each worker clones the repo and works
    on an isolated branch.
    """

    def __init__(self, repo_url: str, clone_path: str, branch: str = ""):
        self._repo_url = repo_url
        self._clone_path = os.path.abspath(clone_path)
        self._branch = branch or f"sf/clone-{os.getpid()}"

    def setup(self) -> str:
        """Clone the repo and create a working branch. Idempotent.

        Returns:
            Absolute path to the clone directory.
        """
        if os.path.isdir(self._clone_path):
            return self._clone_path

        # Clone the repository
        subprocess.run(
            ["git", "clone", self._repo_url, self._clone_path],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )

        # Create and checkout working branch
        self._git("checkout", "-b", self._branch)
        return self._clone_path

    def teardown(self) -> None:
        """Remove the clone directory entirely."""
        if os.path.isdir(self._clone_path):
            shutil.rmtree(self._clone_path, ignore_errors=True)

    def fork(self, name: str) -> "Fixture":
        """Create another clone with a sub-branch.

        Args:
            name: Identifier for the forked clone.

        Returns:
            New GitCloneFixture with a derived branch name.
        """
        fork_path = os.path.join(
            os.path.dirname(self._clone_path),
            f".sf-clone-{name}",
        )
        return GitCloneFixture(
            repo_url=self._repo_url,
            clone_path=fork_path,
            branch=f"{self._branch}/{name}",
        )

    def checkpoint(self, message: str) -> Optional[str]:
        """Commit all changes and push to origin. Returns commit hash or None."""
        try:
            self._git("add", "-A")

            result = self._git("status", "--porcelain")
            if not result.strip():
                return None

            self._git("commit", "-m", message)
            commit_hash = self._git("rev-parse", "HEAD").strip()

            # Push to origin for integration
            try:
                self._git("push", "-u", "origin", self._branch)
            except subprocess.CalledProcessError:
                # Push failure is non-fatal (may be local-only setup)
                pass

            return commit_hash
        except subprocess.CalledProcessError:
            return None

    @property
    def path(self) -> str:
        return self._clone_path

    @property
    def branch(self) -> str:
        return self._branch

    @property
    def repo_url(self) -> str:
        return self._repo_url

    def serialize(self) -> Dict[str, Any]:
        return {
            "type": "git_clone",
            "repo_url": self._repo_url,
            "clone_path": self._clone_path,
            "branch": self._branch,
        }

    @staticmethod
    def _from_dict(data: Dict[str, Any]) -> "GitCloneFixture":
        return GitCloneFixture(
            repo_url=data["repo_url"],
            clone_path=data["clone_path"],
            branch=data.get("branch", ""),
        )

    # --- Internal helpers ---

    def _git(self, *args: str) -> str:
        """Run a git command in the clone directory."""
        result = subprocess.run(
            ["git"] + list(args),
            cwd=self._clone_path,
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
