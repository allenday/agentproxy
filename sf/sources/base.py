"""
SourceAdapter ABC
=================

Abstract base for external demand channels that produce WorkOrders.
Each adapter translates domain-specific events (GitHub issues, Jira tickets,
Prometheus alerts) into the universal WorkOrder format.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SourceEvent(BaseModel):
    """Raw event from an external source before conversion to WorkOrder.

    This is the intermediate representation between the external system's
    native format and our WorkOrder model.
    """

    source_type: str  # "github", "jira", "alert", "cli"
    source_ref: str  # External ID (e.g., "GH#123", "PROJ-456")
    title: str
    body: str = ""
    labels: List[str] = Field(default_factory=list)
    priority: int = 0  # 0=highest
    metadata: Dict[str, Any] = Field(default_factory=dict)
    received_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class SourceAdapter(ABC):
    """Abstract base for external work order sources.

    Subclasses implement:
    - source_type: identifier for this source ("github", "jira", etc.)
    - parse_event(): convert raw webhook/API payload to SourceEvent
    - enrich_work_order(): add source-specific metadata to a WorkOrder
    """

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Identifier for this source type."""
        ...

    @abstractmethod
    def parse_event(self, payload: Dict[str, Any]) -> Optional[SourceEvent]:
        """Parse a raw payload into a SourceEvent.

        Args:
            payload: Raw webhook/API payload from the external system.

        Returns:
            SourceEvent if the payload is actionable, None to skip.
        """
        ...

    def to_work_order_params(self, event: SourceEvent) -> Dict[str, Any]:
        """Convert a SourceEvent to WorkOrder constructor params.

        Returns a dict suitable for WorkOrder(**params).
        Override to customize per-source behavior.

        Args:
            event: Parsed source event.

        Returns:
            Dict of WorkOrder field values.
        """
        return {
            "prompt": self._build_prompt(event),
            "source": self.source_type,
            "source_ref": event.source_ref,
            "required_capabilities": self._infer_capabilities(event),
            "created_at": event.received_at,
        }

    def _build_prompt(self, event: SourceEvent) -> str:
        """Build a work order prompt from a source event.

        Args:
            event: Parsed source event.

        Returns:
            Prompt string for the work order.
        """
        parts = [event.title]
        if event.body:
            parts.append(f"\n\n{event.body}")
        if event.labels:
            parts.append(f"\n\nLabels: {', '.join(event.labels)}")
        return "\n".join(parts)

    def _infer_capabilities(self, event: SourceEvent) -> Dict[str, Any]:
        """Infer required capabilities from source event metadata.

        Override for source-specific capability inference.

        Args:
            event: Parsed source event.

        Returns:
            Dict of required capabilities.
        """
        return {}
