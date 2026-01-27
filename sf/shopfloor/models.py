"""
ShopFloor Models
================

WorkOrder: the universal unit of work (replaces Milestone).
WorkOrderResult: output from a completed work order.
WorkOrderStatus: lifecycle states.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkOrderStatus(str, Enum):
    """Lifecycle states for a WorkOrder."""
    PENDING = "pending"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class WorkOrder:
    """The universal unit of work. Replaces Milestone.

    The DAG of work orders aligns naturally with:
    - Jira: epic → stories → subtasks with dependencies
    - Incident response: detect → investigate → remediate → verify
    - Continuous deployment: build → test → stage → deploy → monitor
    """
    index: int
    prompt: str
    depends_on: List[int] = field(default_factory=list)
    required_capabilities: Dict[str, Any] = field(default_factory=dict)

    # Source tracking — where did this work order come from?
    source: str = "decomposition"  # "decomposition", "jira", "telemetry", "feedback"
    source_ref: Optional[str] = None  # Jira ticket ID, alert ID, etc.

    # State
    status: WorkOrderStatus = WorkOrderStatus.PENDING

    # Timestamps (for lead time / queue time metrics)
    created_at: Optional[str] = None
    dispatched_at: Optional[str] = None
    completed_at: Optional[str] = None

    def serialize(self) -> Dict[str, Any]:
        """Serialize for Celery transport."""
        return {
            "index": self.index,
            "prompt": self.prompt,
            "depends_on": self.depends_on,
            "required_capabilities": self.required_capabilities,
            "source": self.source,
            "source_ref": self.source_ref,
            "status": self.status.value,
            "created_at": self.created_at,
            "dispatched_at": self.dispatched_at,
            "completed_at": self.completed_at,
        }

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "WorkOrder":
        return WorkOrder(
            index=data["index"],
            prompt=data["prompt"],
            depends_on=data.get("depends_on", []),
            required_capabilities=data.get("required_capabilities", {}),
            source=data.get("source", "decomposition"),
            source_ref=data.get("source_ref"),
            status=WorkOrderStatus(data.get("status", "pending")),
            created_at=data.get("created_at"),
            dispatched_at=data.get("dispatched_at"),
            completed_at=data.get("completed_at"),
        )


@dataclass
class WorkOrderResult:
    """Output from a completed work order. Replaces MilestoneResult."""
    status: str  # "completed" or "failed"
    events: List[Dict[str, Any]]  # serialized OutputEvents
    files_changed: List[str]
    summary: str
    duration: float
    work_order_index: int
    capabilities_used: Dict[str, Any] = field(default_factory=dict)

    def serialize(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "events": self.events,
            "files_changed": self.files_changed,
            "summary": self.summary,
            "duration": self.duration,
            "work_order_index": self.work_order_index,
            "capabilities_used": self.capabilities_used,
        }

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "WorkOrderResult":
        return WorkOrderResult(
            status=data["status"],
            events=data.get("events", []),
            files_changed=data.get("files_changed", []),
            summary=data.get("summary", ""),
            duration=data.get("duration", 0.0),
            work_order_index=data["work_order_index"],
            capabilities_used=data.get("capabilities_used", {}),
        )
