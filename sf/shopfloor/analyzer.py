"""
ResultAnalyzer (Kaizen Loop)
============================

Examines WorkOrderResults, IntegrationResults, and InspectionResults.
Generates corrective WorkOrders that feed back into the production queue:
  - source="feedback" for intra-factory defects
  - source="telemetry" for Plane 2 field signals

The Kaizen loop is: Detect -> Dispatch -> Verify -> Learn.
"""

import logging
from typing import Any, Dict, List, Optional

from ..workstation.quality_gate import InspectionResult
from .assembly import IntegrationResult, IntegrationStatus
from .models import WorkOrder, WorkOrderResult

logger = logging.getLogger(__name__)


class ResultAnalyzer:
    """Analyzes production results and generates corrective work orders.

    This is the "Detect" step in the Kaizen loop. It examines:
    - WorkOrderResults: did the task complete? Were there errors?
    - InspectionResults: did quality gates pass?
    - IntegrationResults: were there merge conflicts?

    And generates feedback WorkOrders to correct problems.
    """

    def __init__(self, max_rework_per_wo: int = 3):
        """Initialize analyzer.

        Args:
            max_rework_per_wo: Maximum rework attempts per work order
                before giving up (prevents infinite loops).
        """
        self.max_rework_per_wo = max_rework_per_wo
        self._rework_counts: Dict[int, int] = {}  # wo_index -> count

    def analyze_result(
        self,
        wo: WorkOrder,
        result: WorkOrderResult,
        next_index: int,
    ) -> Optional[WorkOrder]:
        """Analyze a work order result and generate a corrective WO if needed.

        Args:
            wo: The original work order.
            result: The result of executing the work order.
            next_index: Next available work order index.

        Returns:
            A corrective WorkOrder or None if no rework needed.
        """
        if result.status == "completed" and not result.defects:
            return None

        # Check rework limit
        rework_count = self._rework_counts.get(wo.index, 0)
        if rework_count >= self.max_rework_per_wo:
            logger.warning(
                "WO-%d exceeded max rework attempts (%d), skipping",
                wo.index, self.max_rework_per_wo,
            )
            return None

        self._rework_counts[wo.index] = rework_count + 1

        if result.status == "failed":
            return self._create_failure_rework(wo, result, next_index)

        if result.defects:
            return self._create_defect_rework(wo, result, next_index)

        return None

    def analyze_inspection(
        self,
        wo: WorkOrder,
        inspection: InspectionResult,
        next_index: int,
    ) -> Optional[WorkOrder]:
        """Analyze a quality gate inspection and generate a corrective WO.

        Args:
            wo: The work order that was inspected.
            inspection: The inspection result.
            next_index: Next available work order index.

        Returns:
            A corrective WorkOrder or None if inspection passed.
        """
        if inspection.passed:
            return None

        rework_count = self._rework_counts.get(wo.index, 0)
        if rework_count >= self.max_rework_per_wo:
            logger.warning(
                "WO-%d exceeded max rework attempts (%d) after inspection, skipping",
                wo.index, self.max_rework_per_wo,
            )
            return None

        self._rework_counts[wo.index] = rework_count + 1

        defect_summary = "\n".join(f"- {d}" for d in inspection.defects[:5])
        prompt = (
            f"Fix quality gate failures from WO-{wo.index}.\n\n"
            f"Original task: {wo.prompt[:200]}\n\n"
            f"Defects found:\n{defect_summary}\n\n"
            f"Details: {inspection.details[:500]}"
        )

        return WorkOrder(
            index=next_index,
            prompt=prompt,
            depends_on=[],
            source="feedback",
            source_ref=f"rework:WO-{wo.index}:gate",
            sop_name=wo.sop_name,
            priority=max(0, wo.priority - 1),  # Higher priority than original
        )

    def analyze_conflict(
        self,
        integration: IntegrationResult,
        context: Dict[str, Any],
        next_index: int,
    ) -> Optional[WorkOrder]:
        """Analyze a merge conflict and generate a resolution WO.

        Args:
            integration: The IntegrationResult with conflict details.
            context: Additional context (e.g., work order indices involved).
            next_index: Next available work order index.

        Returns:
            A resolution WorkOrder or None if no conflict.
        """
        if integration.status != IntegrationStatus.CONFLICT:
            return None

        prompt = (
            f"Resolve merge conflict in files: {', '.join(integration.conflicted_files)}.\n"
            f"Conflict details:\n{integration.conflict_diff[:2000]}\n"
            f"Context: {context.get('summary', 'parallel work order integration')}"
        )

        return WorkOrder(
            index=next_index,
            prompt=prompt,
            depends_on=[],
            source="feedback",
            source_ref="merge_conflict",
            priority=0,  # Conflicts are high priority
        )

    def _create_failure_rework(
        self,
        wo: WorkOrder,
        result: WorkOrderResult,
        next_index: int,
    ) -> WorkOrder:
        """Create a rework WO for a failed work order."""
        prompt = (
            f"Rework failed WO-{wo.index}.\n\n"
            f"Original task: {wo.prompt[:300]}\n\n"
            f"Failure summary: {result.summary[:500]}\n\n"
            f"Fix the issues and complete the original task."
        )

        return WorkOrder(
            index=next_index,
            prompt=prompt,
            depends_on=[],
            source="feedback",
            source_ref=f"rework:WO-{wo.index}:failure",
            sop_name=wo.sop_name,
            priority=max(0, wo.priority - 1),
        )

    def _create_defect_rework(
        self,
        wo: WorkOrder,
        result: WorkOrderResult,
        next_index: int,
    ) -> WorkOrder:
        """Create a rework WO for defects found during execution."""
        defect_summary = "\n".join(f"- {d}" for d in result.defects[:5])
        prompt = (
            f"Fix defects from WO-{wo.index}.\n\n"
            f"Original task: {wo.prompt[:200]}\n\n"
            f"Defects:\n{defect_summary}\n\n"
            f"Fix these defects while preserving the completed work."
        )

        return WorkOrder(
            index=next_index,
            prompt=prompt,
            depends_on=[],
            source="feedback",
            source_ref=f"rework:WO-{wo.index}:defect",
            sop_name=wo.sop_name,
            priority=max(0, wo.priority - 1),
        )

    @property
    def total_rework_count(self) -> int:
        """Total number of rework attempts across all work orders."""
        return sum(self._rework_counts.values())

    def reset(self) -> None:
        """Reset rework counters."""
        self._rework_counts.clear()
