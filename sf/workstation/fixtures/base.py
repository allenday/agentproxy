"""
Fixture ABC
===========

Abstract base for workpiece holders. Defines the interface for
setup, teardown, fork (parallel isolation), and checkpoint (snapshot).
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class Fixture(ABC):
    """Abstract base for workpiece fixtures (VCS strategy).

    A Fixture manages the working directory where an agent operates.
    Different implementations provide different isolation and VCS strategies.
    """

    @abstractmethod
    def setup(self) -> str:
        """Prepare the fixture and return the working directory path.

        Must be idempotent — calling setup() on an already-setup fixture
        should return the same path without side effects.

        Returns:
            Absolute path to the working directory.
        """

    @abstractmethod
    def teardown(self) -> None:
        """Remove/clean up the fixture.

        For LocalDirFixture: no-op (preserves directory).
        For GitWorktreeFixture: removes worktree and branch.
        For GitCloneFixture: removes clone directory.
        """

    @abstractmethod
    def fork(self, name: str) -> "Fixture":
        """Create an isolated child fixture for parallel production.

        Args:
            name: Identifier for the child fixture (used in branch names, etc.)

        Returns:
            A new Fixture instance isolated from this one.

        Raises:
            NotImplementedError: If the fixture type does not support forking.
        """

    @abstractmethod
    def checkpoint(self, message: str) -> Optional[str]:
        """Snapshot the current state (e.g., git commit).

        Args:
            message: Description of the checkpoint.

        Returns:
            Commit hash or identifier, or None if no changes to snapshot.
        """

    @property
    @abstractmethod
    def path(self) -> str:
        """Absolute path to the working directory."""

    @abstractmethod
    def serialize(self) -> Dict[str, Any]:
        """Serialize fixture state for Celery transport.

        Returns:
            JSON-serializable dict with 'type' key and fixture-specific data.
        """

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "Fixture":
        """Reconstruct a Fixture from serialized data.

        Args:
            data: Dict from serialize(), must contain 'type' key.

        Returns:
            Reconstructed Fixture instance.
        """
        fixture_type = data.get("type")
        if fixture_type == "local_dir":
            from .local_dir import LocalDirFixture
            return LocalDirFixture._from_dict(data)
        elif fixture_type == "git_repo":
            from .git_repo import GitRepoFixture
            return GitRepoFixture._from_dict(data)
        elif fixture_type == "git_worktree":
            from .git_worktree import GitWorktreeFixture
            return GitWorktreeFixture._from_dict(data)
        elif fixture_type == "git_clone":
            from .git_clone import GitCloneFixture
            return GitCloneFixture._from_dict(data)
        else:
            raise ValueError(f"Unknown fixture type: {fixture_type}")
