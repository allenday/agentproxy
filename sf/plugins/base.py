"""
SF Plugin System: Base classes for hook-based plugin architecture.

Defines the ABC, hook phases, result types, and context carrier
for the hook-based plugin system.

Phase 6: All 7 aspirational hooks are now wired and dispatched.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class PluginHookPhase(str, Enum):
    """Hook phases in the PA lifecycle.

    Essential (wired since Phase 2):
        ON_TASK_START, ON_TASK_COMPLETE, ON_TASK_ERROR, ON_PA_DECISION

    Aspirational (Phase 6 -- now wired):
        ON_FUNCTION_PRE, ON_FUNCTION_POST, ON_CLAUDE_START, ON_CLAUDE_COMPLETE,
        ON_VERIFY_START, ON_VERIFY_COMPLETE, ON_FILE_CHANGE
    """

    # Essential -- wired in pa.py
    ON_TASK_START = "on_task_start"
    ON_TASK_COMPLETE = "on_task_complete"
    ON_TASK_ERROR = "on_task_error"
    ON_PA_DECISION = "on_pa_decision"

    # Aspirational -- now wired (Phase 6)
    ON_FUNCTION_PRE = "on_function_pre"
    ON_FUNCTION_POST = "on_function_post"
    ON_CLAUDE_START = "on_claude_start"
    ON_CLAUDE_COMPLETE = "on_claude_complete"
    ON_VERIFY_START = "on_verify_start"
    ON_VERIFY_COMPLETE = "on_verify_complete"
    ON_FILE_CHANGE = "on_file_change"


@dataclass(frozen=True)
class PluginResult:
    """Outcome of a plugin hook execution.

    Use factory methods: ok(), block(message), modify(data).
    """

    action: str  # "continue", "block", "modify"
    message: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def ok() -> "PluginResult":
        """Continue normally."""
        return PluginResult(action="continue")

    @staticmethod
    def block(message: str) -> "PluginResult":
        """Block the current operation."""
        return PluginResult(action="block", message=message)

    @staticmethod
    def modify(data: Dict[str, Any]) -> "PluginResult":
        """Modify context data for downstream processing."""
        return PluginResult(action="modify", data=data)


@dataclass(frozen=True)
class PluginContext:
    """Read-only data carrier passed to plugin hooks.

    Cross-hook state lives on the plugin instance (instance variables),
    not on PluginContext.
    """

    phase: PluginHookPhase
    data: Dict[str, Any] = field(default_factory=dict)


class SFPlugin:
    """Abstract base class for SF plugins.

    Subclasses must implement `name`. Override specific hook methods
    to receive those hooks. The base class provides default no-op
    implementations that return PluginResult.ok().

    All 11 hooks are now wired and dispatched:
    - 4 essential hooks (Phase 2)
    - 7 aspirational hooks (Phase 6)

    Example::

        class MyPlugin(SFPlugin):
            @property
            def name(self) -> str:
                return "my-plugin"

            def on_task_start(self, ctx: PluginContext) -> PluginResult:
                print(f"Task started with data: {ctx.data}")
                return PluginResult.ok()

            def on_claude_start(self, ctx: PluginContext) -> PluginResult:
                print(f"Claude starting: {ctx.data.get('instruction', '')[:50]}")
                return PluginResult.ok()
    """

    @property
    def name(self) -> str:
        """Unique plugin name. Must be implemented by subclass."""
        raise NotImplementedError

    @property
    def version(self) -> str:
        """Plugin version. Override to customize."""
        return "0.1.0"

    def on_init(self, pa: Any) -> None:
        """Called once after plugin is loaded with a reference to PA.

        Override to perform initialization that needs access to PA state.
        """
        pass

    def supports_hook(self, phase: PluginHookPhase) -> bool:
        """Check if this plugin handles the given hook phase.

        Returns True if the subclass overrides the corresponding method
        (i.e., it's not the default base class implementation).
        """
        method_name = _PHASE_TO_METHOD.get(phase)
        if method_name is None:
            return False
        own_method = getattr(type(self), method_name, None)
        base_method = getattr(SFPlugin, method_name, None)
        return own_method is not base_method

    def execute_hook(self, ctx: PluginContext) -> PluginResult:
        """Dispatch to the appropriate hook method based on phase."""
        method_name = _PHASE_TO_METHOD.get(ctx.phase)
        if method_name is None:
            return PluginResult.ok()
        handler = getattr(self, method_name, None)
        if handler is None:
            return PluginResult.ok()
        return handler(ctx)

    # =========================================================================
    # Essential hooks (wired since Phase 2)
    # =========================================================================

    def on_task_start(self, ctx: PluginContext) -> PluginResult:
        """Called before task execution begins.

        Context data: session_id, task, working_dir
        """
        return PluginResult.ok()

    def on_task_complete(self, ctx: PluginContext) -> PluginResult:
        """Called after task completes successfully.

        Context data: session_id, task, files_changed_count
        """
        return PluginResult.ok()

    def on_task_error(self, ctx: PluginContext) -> PluginResult:
        """Called when task encounters an error.

        Context data: session_id, task, error
        """
        return PluginResult.ok()

    def on_pa_decision(self, ctx: PluginContext) -> PluginResult:
        """Called after each PA reasoning cycle.

        Context data: decision, function_name, iteration
        """
        return PluginResult.ok()

    # =========================================================================
    # Aspirational hooks (Phase 6 -- now wired)
    # =========================================================================

    def on_function_pre(self, ctx: PluginContext) -> PluginResult:
        """Called before FunctionExecutor.execute().

        Context data: function_name, arguments
        """
        return PluginResult.ok()

    def on_function_post(self, ctx: PluginContext) -> PluginResult:
        """Called after FunctionExecutor.execute().

        Context data: function_name, success, duration
        """
        return PluginResult.ok()

    def on_claude_start(self, ctx: PluginContext) -> PluginResult:
        """Called before PA._stream_claude() begins streaming.

        Context data: instruction, iteration, working_dir
        """
        return PluginResult.ok()

    def on_claude_complete(self, ctx: PluginContext) -> PluginResult:
        """Called after PA._stream_claude() completes.

        Context data: instruction, event_count, working_dir
        """
        return PluginResult.ok()

    def on_verify_start(self, ctx: PluginContext) -> PluginResult:
        """Called before quality gate inspection begins.

        Context data: gate_type, work_order_index
        """
        return PluginResult.ok()

    def on_verify_complete(self, ctx: PluginContext) -> PluginResult:
        """Called after quality gate inspection completes.

        Context data: gate_type, passed, defects
        """
        return PluginResult.ok()

    def on_file_change(self, ctx: PluginContext) -> PluginResult:
        """Called when a file tool (Write, Edit) modifies a file.

        Context data: tool_name, file_path, change_type
        """
        return PluginResult.ok()


# Phase -> method name mapping (used by supports_hook and execute_hook)
_PHASE_TO_METHOD = {
    PluginHookPhase.ON_TASK_START: "on_task_start",
    PluginHookPhase.ON_TASK_COMPLETE: "on_task_complete",
    PluginHookPhase.ON_TASK_ERROR: "on_task_error",
    PluginHookPhase.ON_PA_DECISION: "on_pa_decision",
    PluginHookPhase.ON_FUNCTION_PRE: "on_function_pre",
    PluginHookPhase.ON_FUNCTION_POST: "on_function_post",
    PluginHookPhase.ON_CLAUDE_START: "on_claude_start",
    PluginHookPhase.ON_CLAUDE_COMPLETE: "on_claude_complete",
    PluginHookPhase.ON_VERIFY_START: "on_verify_start",
    PluginHookPhase.ON_VERIFY_COMPLETE: "on_verify_complete",
    PluginHookPhase.ON_FILE_CHANGE: "on_file_change",
}
