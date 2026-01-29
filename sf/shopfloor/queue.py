"""
WorkOrderQueue (Priority Queue)
================================

Priority queue for work orders. Enables the continuous-flow Kaizen loop:
feedback WOs are enqueued with higher priority than original WOs.

Priority ordering (lower number = higher priority):
  0: feedback (intra-factory defects, merge conflicts)
  1: telemetry (Plane 2 field signals)
  2: jira, github (external demand)
  3: decomposition (BOM-generated)

The ShopFloor drains this queue between layers.
"""

import heapq
import logging
import threading
from typing import List, Optional

from .models import WorkOrder

logger = logging.getLogger(__name__)

# Source type to default priority mapping
SOURCE_PRIORITY: dict = {
    "feedback": 0,
    "telemetry": 1,
    "jira": 2,
    "github": 2,
    "cli": 2,
    "decomposition": 3,
}


class WorkOrderQueue:
    """Thread-safe priority queue for work orders.

    Work orders are dequeued in priority order (lower number = higher priority).
    Within the same priority, FIFO ordering is maintained via a sequence counter.
    """

    def __init__(self) -> None:
        self._heap: List[tuple] = []  # (priority, seq, WorkOrder)
        self._seq: int = 0
        self._lock = threading.Lock()

    def enqueue(self, wo: WorkOrder) -> None:
        """Add a work order to the queue.

        Priority is determined by:
        1. WorkOrder.priority field (if set)
        2. SOURCE_PRIORITY mapping based on source type
        3. Default priority of 3

        Args:
            wo: Work order to enqueue.
        """
        priority = wo.priority
        if priority is None or priority < 0:
            priority = SOURCE_PRIORITY.get(wo.source, 3)

        with self._lock:
            heapq.heappush(self._heap, (priority, self._seq, wo))
            self._seq += 1

    def enqueue_many(self, work_orders: List[WorkOrder]) -> None:
        """Enqueue multiple work orders.

        Args:
            work_orders: List of work orders to enqueue.
        """
        for wo in work_orders:
            self.enqueue(wo)

    def dequeue(self) -> Optional[WorkOrder]:
        """Remove and return the highest-priority work order.

        Returns:
            WorkOrder or None if queue is empty.
        """
        with self._lock:
            if not self._heap:
                return None
            _, _, wo = heapq.heappop(self._heap)
            return wo

    def dequeue_batch(self, max_size: int = 10) -> List[WorkOrder]:
        """Dequeue up to max_size work orders.

        Args:
            max_size: Maximum number of work orders to dequeue.

        Returns:
            List of work orders (may be empty).
        """
        batch = []
        for _ in range(max_size):
            wo = self.dequeue()
            if wo is None:
                break
            batch.append(wo)
        return batch

    def peek(self) -> Optional[WorkOrder]:
        """Look at the highest-priority work order without removing it.

        Returns:
            WorkOrder or None if queue is empty.
        """
        with self._lock:
            if not self._heap:
                return None
            _, _, wo = self._heap[0]
            return wo

    @property
    def size(self) -> int:
        """Number of work orders in the queue."""
        with self._lock:
            return len(self._heap)

    @property
    def empty(self) -> bool:
        """Whether the queue is empty."""
        with self._lock:
            return len(self._heap) == 0

    def clear(self) -> None:
        """Remove all work orders from the queue."""
        with self._lock:
            self._heap.clear()
            self._seq = 0
