import os
from typing import Iterable


def ensure_gitignore(path: str, entries: Iterable[str]) -> None:
    """
    Ensure .gitignore exists at path and contains the provided entries.

    Idempotent: only appends missing lines, preserves existing content.
    """
    ignore_path = os.path.join(path, ".gitignore")
    existing = []
    if os.path.isfile(ignore_path):
        with open(ignore_path, "r", encoding="utf-8") as f:
            existing = [line.rstrip("\n") for line in f.readlines()]

    to_add = []
    for entry in entries:
        if entry not in existing:
            to_add.append(entry)

    if to_add or not os.path.isfile(ignore_path):
        with open(ignore_path, "a", encoding="utf-8") as f:
            for entry in to_add:
                f.write(entry + "\n")

