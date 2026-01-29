"""
ShopFloor Models
================

WorkOrder: the universal unit of work (replaces Milestone).
WorkOrderResult: output from a completed work order.
WorkOrderStatus: lifecycle states.

v0 SOP: All models use Pydantic BaseModel (not dataclass).
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WorkOrderStatus(str, Enum):
    """Lifecycle states for a WorkOrder."""
    PENDING = "pending"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkOrder(BaseModel):
    """The universal unit of work. Replaces Milestone.

    The DAG of work orders aligns naturally with:
    - Jira: epic -> stories -> subtasks with dependencies
    - Incident response: detect -> investigate -> remediate -> verify
    - Continuous deployment: build -> test -> stage -> deploy -> monitor
    """
    index: int
    prompt: str
    depends_on: List[int] = Field(default_factory=list)
    required_capabilities: Dict[str, Any] = Field(default_factory=dict)

    # Source tracking -- where did this work order come from?
    source: str = "decomposition"  # "decomposition", "jira", "telemetry", "feedback", "cli", "github"
    source_ref: Optional[str] = None  # Jira ticket ID, alert ID, GH#123, etc.

    # State
    status: WorkOrderStatus = WorkOrderStatus.PENDING

    # Timestamps (for lead time / queue time metrics)
    created_at: Optional[str] = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
    )
    dispatched_at: Optional[str] = None
    completed_at: Optional[str] = None

    # SOP to apply (name from SOP registry)
    sop_name: Optional[str] = None

    # Priority (lower = higher priority, used by WorkOrderQueue)
    priority: int = 2

    def serialize(self) -> Dict[str, Any]:
        """Serialize for Celery transport."""
        return self.model_dump(mode="json")

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "WorkOrder":
        return WorkOrder(**data)


class WorkOrderResult(BaseModel):
    """Output from a completed work order. Replaces MilestoneResult."""
    status: str  # "completed" or "failed"
    events: List[Dict[str, Any]] = Field(default_factory=list)
    files_changed: List[str] = Field(default_factory=list)
    summary: str = ""
    duration: float = 0.0
    work_order_index: int = 0
    capabilities_used: Dict[str, Any] = Field(default_factory=dict)

    # Defects found by quality gates
    defects: List[str] = Field(default_factory=list)

    def serialize(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "WorkOrderResult":
        return WorkOrderResult(**data)
