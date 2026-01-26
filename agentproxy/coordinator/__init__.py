"""
Coordinator Package
===================

Multi-worker coordination for agentproxy using Celery + Redis.
This is an optional dependency -- if celery is not installed,
agentproxy runs in single-worker mode as before.

Exports:
    Coordinator: Orchestrates task decomposition and milestone dispatch.
    is_celery_available: Returns True if Celery workers are active.
"""

from .coordinator import Coordinator


def _packages_importable() -> bool:
    """Return True if both ``celery`` and ``redis`` packages can be imported."""
    try:
        import celery  # noqa: F401
        import redis  # noqa: F401
        return True
    except ImportError:
        return False


def is_celery_available() -> bool:
    """Check whether Celery workers are actually running.

    Returns True only when:
    1. ``celery`` and ``redis`` packages are importable, AND
    2. At least one Celery worker responds to a ping.

    The ping uses a short timeout (2 s) so the caller does not block
    for long when no infrastructure is present.
    """
    if not _packages_importable():
        return False

    try:
        from .celery_app import make_celery_app

        app = make_celery_app()
        inspect = app.control.inspect(timeout=2)
        pong = inspect.ping()
        return bool(pong)
    except Exception:
        return False


from .models import Milestone  # noqa: F401

__all__ = ["Coordinator", "Milestone", "is_celery_available"]
