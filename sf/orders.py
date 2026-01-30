"""
Order models to separate user-facing workorders from internal travelers.

- ExternalOrder: parsed/validated user input (frontmatter + body).
- Traveler: expanded, fully-specified internal instructions for ShopFloor/Workstation.
"""

from typing import Dict, Any
from pydantic import BaseModel

from .workstation.frontmatter import (
    parse_frontmatter,
    validate_frontmatter,
    expand_templates,
    validate_internal,
    FrontmatterError,
)


class ExternalOrder(BaseModel):
    meta: Dict[str, Any]
    body: str

    model_config = {"arbitrary_types_allowed": True}


class Traveler(BaseModel):
    meta: Dict[str, Any]
    body: str

    model_config = {"arbitrary_types_allowed": True}


def make_external_order(task_text: str) -> ExternalOrder:
    """Parse and minimally validate user-supplied workorder."""
    meta, body = parse_frontmatter(task_text)
    validate_frontmatter(meta)
    return ExternalOrder(meta=meta, body=body)


def make_traveler(order: ExternalOrder) -> Traveler:
    """Expand templates and run strict internal validation."""
    expanded = expand_templates(order.meta)
    validate_internal(expanded)
    return Traveler(meta=expanded, body=order.body)
