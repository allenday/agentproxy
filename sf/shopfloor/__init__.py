"""
ShopFloor Package
=================

Manufacturing-inspired agent orchestration.
Replaces coordinator/ with shopfloor/.
"""

from .models import WorkOrder, WorkOrderResult, WorkOrderStatus
from .routing import build_layers, match_capabilities, parse_work_orders
from .assembly import AssemblyStation, IntegrationResult, IntegrationStatus
from .shopfloor import ShopFloor

__all__ = [
    "ShopFloor",
    "WorkOrder",
    "WorkOrderResult",
    "WorkOrderStatus",
    "AssemblyStation",
    "IntegrationResult",
    "IntegrationStatus",
    "build_layers",
    "match_capabilities",
    "parse_work_orders",
]


def is_celery_available() -> bool:
    """Check if Celery workers are available for distributed dispatch.

    Returns True only if:
    1. celery and redis packages are importable
    2. At least one worker responds to ping
    """
    if not _packages_importable():
        return False

    try:
        from .celery_app import make_celery_app
        app = make_celery_app()
        result = app.control.ping(timeout=2)
        return bool(result)
    except Exception:
        return False


def _packages_importable() -> bool:
    """Check if celery and redis packages are installed."""
    try:
        import celery  # noqa: F401
        import redis  # noqa: F401
        return True
    except ImportError:
        return False
