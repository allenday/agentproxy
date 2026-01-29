"""
Worker CLI
==========

Entry point for starting a Celery worker that processes work orders.

Usage:
    sf-worker                                         # Start worker with defaults
    sf-worker --concurrency 4                         # Start with 4 concurrent workers
    sf-worker --queue gpu                             # Listen on 'gpu' queue
    sf-worker --capability language:python             # Advertise Python capability
    sf-worker --capability context_window:200000       # Advertise context window
    sf-worker --sop v0                                # Set default SOP for tasks
"""

import argparse
import json
import logging
import sys
from typing import Dict


def parse_capability(cap_str: str) -> tuple:
    """Parse a capability string like 'key:value' into (key, value).

    Values are auto-coerced: 'true'/'false' -> bool, numeric -> int/float.
    """
    if ":" not in cap_str:
        return cap_str, True

    key, value = cap_str.split(":", 1)
    key = key.strip()
    value = value.strip()

    # Boolean coercion
    if value.lower() == "true":
        return key, True
    if value.lower() == "false":
        return key, False

    # Numeric coercion
    try:
        return key, int(value)
    except ValueError:
        pass
    try:
        return key, float(value)
    except ValueError:
        pass

    return key, value


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
    parser.add_argument(
        "--capability",
        action="append",
        default=[],
        metavar="KEY:VALUE",
        help="Advertise a capability (e.g., language:python, gpu:true). Repeatable.",
    )
    parser.add_argument(
        "--sop",
        default=None,
        help="Default SOP name for tasks (e.g., v0, hotfix). From SOP registry.",
    )
    parser.add_argument(
        "--capabilities-file",
        default=None,
        help="Path to JSON file with WorkstationCapabilities fields.",
    )
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.loglevel.upper()),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger = logging.getLogger("sf.worker")

    try:
        from .celery_app import make_celery_app
    except ImportError:
        print("Error: celery and redis packages required.", file=sys.stderr)
        print("Install with: pip install sf[worker]", file=sys.stderr)
        return 1

    # Parse capabilities
    capabilities: Dict = {}
    for cap_str in args.capability:
        key, value = parse_capability(cap_str)
        # Handle list-type capabilities (language -> languages)
        if key in ("language", "languages"):
            capabilities.setdefault("languages", []).append(str(value))
        elif key in ("tool", "tools"):
            capabilities.setdefault("tools", []).append(str(value))
        elif key in ("package_manager", "package_managers"):
            capabilities.setdefault("package_managers", []).append(str(value))
        else:
            capabilities[key] = value

    # Load from file if provided
    if args.capabilities_file:
        try:
            with open(args.capabilities_file) as f:
                file_caps = json.load(f)
            capabilities.update(file_caps)
            logger.info("Loaded capabilities from %s", args.capabilities_file)
        except Exception as e:
            logger.warning("Failed to load capabilities file: %s", e)

    if capabilities:
        logger.info("Worker capabilities: %s", capabilities)

    # Validate SOP
    if args.sop:
        from ..workstation.sop import get_sop
        sop = get_sop(args.sop)
        if sop:
            logger.info("Default SOP: %s", args.sop)
        else:
            logger.warning("SOP '%s' not found in registry", args.sop)

    app = make_celery_app()

    # Import tasks to register them with the app
    from . import tasks  # noqa: F401

    # Store capabilities and SOP in app config for task access
    app.conf.update({
        "sf_worker_capabilities": capabilities,
        "sf_worker_sop": args.sop,
    })

    argv = [
        "worker",
        f"--concurrency={args.concurrency}",
        f"--queues={args.queue}",
        f"--loglevel={args.loglevel}",
        "--hostname=sf-worker@%h",
    ]
    logger.info("Starting Celery worker on queue '%s'", args.queue)
    app.worker_main(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
