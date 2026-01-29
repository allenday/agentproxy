"""
CLI Source Adapter
==================

Converts direct CLI/API input into WorkOrders.
This is the synchronous human-input channel for when a user
directly submits a task via the CLI or HTTP API.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import SourceAdapter, SourceEvent


class CLISourceAdapter(SourceAdapter):
    """Converts direct human input into WorkOrders."""

    @property
    def source_type(self) -> str:
        return "cli"

    def parse_event(self, payload: Dict[str, Any]) -> Optional[SourceEvent]:
        """Parse a CLI/API submission.

        Expected payload format:
            {
                "task": "Implement feature X",
                "labels": ["python"],
                "sop": "v0",
                "capabilities": {"languages": ["python"]},
            }

        Args:
            payload: CLI input dict.

        Returns:
            SourceEvent (always returns one for valid input).
        """
        task = payload.get("task", "").strip()
        if not task:
            return None

        labels = payload.get("labels", [])
        sop = payload.get("sop")

        return SourceEvent(
            source_type="cli",
            source_ref=f"CLI:{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            title=task,
            body=payload.get("description", ""),
            labels=labels,
            priority=payload.get("priority", 2),
            metadata={
                "sop": sop,
                "capabilities": payload.get("capabilities", {}),
                "user": payload.get("user", ""),
                "working_dir": payload.get("working_dir", ""),
            },
        )

    def _infer_capabilities(self, event: SourceEvent) -> Dict[str, Any]:
        """Use explicitly provided capabilities from CLI input."""
        return event.metadata.get("capabilities", {})

    def infer_sop(self, event: SourceEvent) -> Optional[str]:
        """Use explicitly provided SOP from CLI input.

        Args:
            event: Parsed CLI event.

        Returns:
            SOP name or None.
        """
        return event.metadata.get("sop")
