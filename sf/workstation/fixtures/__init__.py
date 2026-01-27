"""
Fixture Package
===============

Fixtures hold the workpiece (codebase) and define the VCS strategy.
"""

from .base import Fixture
from .local_dir import LocalDirFixture
from .git_repo import GitRepoFixture
from .git_worktree import GitWorktreeFixture
from .git_clone import GitCloneFixture

__all__ = [
    "Fixture",
    "LocalDirFixture",
    "GitRepoFixture",
    "GitWorktreeFixture",
    "GitCloneFixture",
]
