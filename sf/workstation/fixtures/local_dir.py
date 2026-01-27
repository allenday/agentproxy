"""
LocalDirFixture
===============

Simplest fixture: a local directory with no VCS.
Does not support forking (parallel isolation).
"""

import os
from typing import Any, Dict, Optional

from .base import Fixture


class LocalDirFixture(Fixture):
    """Local directory fixture with no VCS management.

    - setup(): creates directory if missing, returns path.
    - teardown(): no-op (preserves the directory).
    - fork(): raises NotImplementedError.
    - checkpoint(): no-op, returns None.
    """

    def __init__(self, path: str):
        self._path = os.path.abspath(path)

    def setup(self) -> str:
        """Create the directory if it doesn't exist. Idempotent."""
        os.makedirs(self._path, exist_ok=True)
        return self._path

    def teardown(self) -> None:
        """No-op — preserves the directory."""
        pass

    def fork(self, name: str) -> "Fixture":
        """LocalDirFixture does not support forking."""
        raise NotImplementedError(
            "LocalDirFixture does not support fork(). "
            "Use GitRepoFixture for parallel isolation via worktrees."
        )

    def checkpoint(self, message: str) -> Optional[str]:
        """No-op — no VCS to snapshot."""
        return None

    @property
    def path(self) -> str:
        return self._path

    def serialize(self) -> Dict[str, Any]:
        return {
            "type": "local_dir",
            "path": self._path,
        }

    @staticmethod
    def _from_dict(data: Dict[str, Any]) -> "LocalDirFixture":
        return LocalDirFixture(path=data["path"])
