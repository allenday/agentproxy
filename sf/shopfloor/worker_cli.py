"""
Worker CLI
==========

Entry point for starting a Celery worker that processes work orders.

Usage:
    sf-worker                     # Start worker with defaults
    sf-worker --concurrency 4     # Start with 4 concurrent workers
    sf-worker --queue gpu         # Listen on 'gpu' queue
"""

import argparse
import sys


def main():
    """Start a Celery worker for ShopFloor work order dispatch."""
    parser = argparse.ArgumentParser(
        prog="sf-worker",
        description="ShopFloor Celery worker for distributed work order dispatch",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Number of concurrent worker processes (default: 2)",
    )
    parser.add_argument(
        "--queue",
        default="default",
        help="Celery queue to listen on (default: default)",
    )
    parser.add_argument(
        "--loglevel",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Log level (default: info)",
    )
    args = parser.parse_args()

    try:
        from .celery_app import make_celery_app
    except ImportError:
        print("Error: celery and redis packages required.", file=sys.stderr)
        print("Install with: pip install sf[worker]", file=sys.stderr)
        return 1

    app = make_celery_app()

    # Import tasks to register them with the app
    from . import tasks  # noqa: F401

    argv = [
        "worker",
        f"--concurrency={args.concurrency}",
        f"--queues={args.queue}",
        f"--loglevel={args.loglevel}",
        "--hostname=sf-worker@%h",
    ]
    app.worker_main(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
