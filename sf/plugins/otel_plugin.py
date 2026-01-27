"""
Demonstration OTEL plugin.

Auto-loaded when SF_ENABLE_TELEMETRY=1. Hooks into task start/complete/error
with log messages via the existing telemetry singleton.

Does NOT replace the inline OTEL instrumentation already present in pa.py.
"""

from typing import Any

from .base import PluginContext, PluginHookPhase, PluginResult, SFPlugin


class OTELPlugin(SFPlugin):
    """Thin OTEL demonstration plugin.

    Logs task lifecycle events through the sf telemetry singleton.
    Complements (does not replace) the existing inline instrumentation.
    """

    @property
    def name(self) -> str:
        return "otel"

    @property
    def version(self) -> str:
        return "0.1.0"

    def on_init(self, pa: Any) -> None:
        from ..telemetry import get_telemetry

        telemetry = get_telemetry()
        telemetry.log(f"[plugin:otel] Initialized for session {getattr(pa, 'session_id', 'unknown')}")

    def on_task_start(self, ctx: PluginContext) -> PluginResult:
        from ..telemetry import get_telemetry

        telemetry = get_telemetry()
        task = ctx.data.get("task", "")
        session_id = ctx.data.get("session_id", "")
        telemetry.log(f"[plugin:otel] Task started: {task[:80]} (session={session_id[:8]})")
        return PluginResult.ok()

    def on_task_complete(self, ctx: PluginContext) -> PluginResult:
        from ..telemetry import get_telemetry

        telemetry = get_telemetry()
        status = ctx.data.get("status", "unknown")
        files = ctx.data.get("files_changed", [])
        telemetry.log(f"[plugin:otel] Task completed: status={status}, files_changed={len(files)}")
        return PluginResult.ok()

    def on_task_error(self, ctx: PluginContext) -> PluginResult:
        from ..telemetry import get_telemetry

        telemetry = get_telemetry()
        error = ctx.data.get("error", "unknown")
        telemetry.log(f"[plugin:otel] Task error: {error[:200]}")
        return PluginResult.ok()

    def on_pa_decision(self, ctx: PluginContext) -> PluginResult:
        from ..telemetry import get_telemetry

        telemetry = get_telemetry()
        decision = ctx.data.get("decision", "unknown")
        function = ctx.data.get("function", "unknown")
        iteration = ctx.data.get("iteration", -1)
        telemetry.log(f"[plugin:otel] PA decision: {decision} -> {function} (iter={iteration})")
        return PluginResult.ok()
