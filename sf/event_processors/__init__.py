"""
Event Processors
================

Processes Claude's stream-json events and extracts structured
enrichments for telemetry.

Modules:
    tool_use  — Processes tool_use events (Bash, Write, Read, etc.)
"""

from .tool_use import (  # noqa: F401
    ALLOWED_LABEL_KEYS,
    BaseToolUseEventProcessor,
    ToolEnrichment,
    get_processor,
    process_tool_event,
    register_processor,
)
