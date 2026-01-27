"""
Celery Application Factory
===========================

Creates and configures a Celery app for distributed work order dispatch.
Uses Redis as both broker and result backend.

Environment variables:
    SF_CELERY_BROKER_URL: Redis broker URL (default: redis://localhost:6379/0)
    SF_CELERY_RESULT_BACKEND: Redis result backend (default: redis://localhost:6379/1)
"""

import os

_DEFAULT_BROKER = "redis://localhost:6379/0"
_DEFAULT_BACKEND = "redis://localhost:6379/1"


def make_celery_app():
    """Create and configure a Celery application.

    Returns:
        Configured Celery app instance.
    """
    from celery import Celery

    broker_url = os.getenv("SF_CELERY_BROKER_URL", _DEFAULT_BROKER)
    result_backend = os.getenv("SF_CELERY_RESULT_BACKEND", _DEFAULT_BACKEND)

    app = Celery(
        "sf.shopfloor",
        broker=broker_url,
        backend=result_backend,
    )

    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
    )

    return app
