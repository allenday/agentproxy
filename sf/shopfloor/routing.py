"""
ShopFloor Routing
=================

Pure functions for work order parsing, dependency graph operations,
and capability matching. Extracted from coordinator logic.

- parse_work_orders(): parse Gemini breakdown into WorkOrders
- build_layers(): topological sort into execution layers (Kahn's algorithm)
- match_capabilities(): check if available capabilities satisfy requirements
"""

import re
from collections import defaultdict, deque
from typing import Any, Dict, List, Tuple

from .models import WorkOrder


def parse_work_orders(breakdown_text: str) -> List[WorkOrder]:
    """Parse Gemini breakdown with (depends: N) annotations into WorkOrders.

    Supports formats:
        1. Step description (depends: 2, 3)
        - Step description (depends: 1)
        Step 1: description

    Dependency numbers are 1-based step numbers, converted to 0-based indices.
    If no dependency annotations found, creates a sequential chain.

    Args:
        breakdown_text: Raw text from Gemini task breakdown.

    Returns:
        List of WorkOrder instances with dependency DAG.
    """
    lines = breakdown_text.strip().split("\n")
    work_orders: List[WorkOrder] = []
    step_pattern = re.compile(
        r"^\s*(?:(\d+)[.):\s]|[-*]\s*(?:Step\s*(\d+)[.:)]?\s*)?)"
    )
    dep_pattern = re.compile(r"\(depends?:\s*([\d,\s]+)\)", re.IGNORECASE)

    idx = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if this looks like a step line
        step_match = step_pattern.match(line)
        if not step_match:
            continue

        # Extract the prompt (strip step number and dep annotation)
        prompt = line
        # Remove leading number/bullet
        prompt = re.sub(r"^\s*(?:\d+[.):\s]|[-*]\s*(?:Step\s*\d+[.:)]?\s*)?)", "", prompt).strip()

        # Extract dependencies
        depends_on: List[int] = []
        dep_match = dep_pattern.search(line)
        if dep_match:
            dep_str = dep_match.group(1)
            for d in dep_str.split(","):
                d = d.strip()
                if d.isdigit():
                    # Convert 1-based step number to 0-based index
                    depends_on.append(int(d) - 1)
            # Remove the dependency annotation from prompt
            prompt = dep_pattern.sub("", prompt).strip()

        if not prompt:
            continue

        work_orders.append(WorkOrder(
            index=idx,
            prompt=prompt,
            depends_on=depends_on,
        ))
        idx += 1

    # If no dependency annotations found, create sequential chain
    if work_orders and not any(wo.depends_on for wo in work_orders):
        for i in range(1, len(work_orders)):
            work_orders[i].depends_on = [i - 1]

    return work_orders


def build_layers(work_orders: List[WorkOrder]) -> List[List[WorkOrder]]:
    """Topological sort into execution layers (Kahn's algorithm).

    Each layer contains work orders that can execute in parallel.
    Layers are ordered: all dependencies of layer N are in layers < N.

    Breaks cycles by releasing the lowest-index work order.

    Args:
        work_orders: List of WorkOrders with depends_on fields.

    Returns:
        List of layers, each layer is a list of WorkOrders.
    """
    if not work_orders:
        return []

    n = len(work_orders)
    wo_map = {wo.index: wo for wo in work_orders}
    valid_indices = set(wo_map.keys())

    # Build adjacency: in_degree[i] = number of deps for work order i
    in_degree: Dict[int, int] = {wo.index: 0 for wo in work_orders}
    dependents: Dict[int, List[int]] = defaultdict(list)

    for wo in work_orders:
        for dep in wo.depends_on:
            if dep in valid_indices:
                in_degree[wo.index] += 1
                dependents[dep].append(wo.index)

    layers: List[List[WorkOrder]] = []
    remaining = set(wo_map.keys())

    while remaining:
        # Find all work orders with zero in-degree
        ready = sorted([idx for idx in remaining if in_degree.get(idx, 0) == 0])

        if not ready:
            # Cycle detected — break by releasing lowest index
            ready = [min(remaining)]

        layer = [wo_map[idx] for idx in ready]
        layers.append(layer)

        for idx in ready:
            remaining.discard(idx)
            for dep_idx in dependents.get(idx, []):
                if dep_idx in remaining:
                    in_degree[dep_idx] = max(0, in_degree[dep_idx] - 1)

    return layers


def match_capabilities(
    required: Dict[str, Any],
    available: Dict[str, Any],
) -> bool:
    """Check if available capabilities satisfy requirements.

    Supports:
    - Exact match: required["gpu"] == True, available["gpu"] == True
    - Min threshold: required["context_window"] == {"min": 200000}
    - Missing capability: returns False

    Args:
        required: WorkOrder.required_capabilities
        available: Workstation.capabilities ∪ Agent.capabilities

    Returns:
        True if all requirements are met.
    """
    for key, req in required.items():
        if key not in available:
            return False
        avail = available[key]
        if isinstance(req, dict) and "min" in req:
            if avail < req["min"]:
                return False
        elif avail != req:
            return False
    return True
