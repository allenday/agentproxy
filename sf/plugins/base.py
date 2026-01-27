"""
Plugin base classes for SF Plugin Architecture.

Defines the ABC, hook phases, result types, and context carrier
for the hook-based plugin system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class PluginHookPhase(str, Enum):
    """Hook phases in the PA lifecycle.

    Essential (wired in v1):
        ON_TASK_START, ON_TASK_COMPLETE, ON_TASK_ERROR, ON_PA_DECISION

    Aspirational (defined for forward compat, NOT wired yet):
        ON_FUNCTION_PRE, ON_FUNCTION_POST, ON_CLAUDE_START, ON_CLAUDE_COMPLETE,
        ON_VERIFY_START, ON_VERIFY_COMPLETE, ON_FILE_CHANGE
    """

    # Essential — wired in pa.py
    ON_TASK_START = "on_task_start"
    ON_TASK_COMPLETE = "on_task_complete"
    ON_TASK_ERROR = "on_task_error"
    ON_PA_DECISION = "on_pa_decision"

    # Aspirational — NOT wired yet
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


class SFPlugin(ABC):
    """Abstract base class for SF plugins.

    Subclasses must implement `name`. Override specific hook methods
    (on_task_start, on_task_complete, on_task_error, on_pa_decision)
    to receive those hooks. The base class provides default no-op
    implementations that return PluginResult.ok().

    Example::

        class MyPlugin(SFPlugin):
            @property
            def name(self) -> str:
                return "my-plugin"

            def on_task_start(self, ctx: PluginContext) -> PluginResult:
                print(f"Task started with data: {ctx.data}")
                return PluginResult.ok()
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin name."""
        ...

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
        method_map = {
            PluginHookPhase.ON_TASK_START: "on_task_start",
            PluginHookPhase.ON_TASK_COMPLETE: "on_task_complete",
            PluginHookPhase.ON_TASK_ERROR: "on_task_error",
            PluginHookPhase.ON_PA_DECISION: "on_pa_decision",
        }
        method_name = method_map.get(phase)
        if method_name is None:
            return False
        # Check if the method on this instance's class differs from SFPlugin's default
        own_method = getattr(type(self), method_name, None)
        base_method = getattr(SFPlugin, method_name, None)
        return own_method is not base_method

    def execute_hook(self, ctx: PluginContext) -> PluginResult:
        """Dispatch to the appropriate hook method based on phase."""
        dispatch = {
            PluginHookPhase.ON_TASK_START: self.on_task_start,
            PluginHookPhase.ON_TASK_COMPLETE: self.on_task_complete,
            PluginHookPhase.ON_TASK_ERROR: self.on_task_error,
            PluginHookPhase.ON_PA_DECISION: self.on_pa_decision,
        }
        handler = dispatch.get(ctx.phase)
        if handler is None:
            return PluginResult.ok()
        return handler(ctx)

    # Default no-op implementations for essential hooks

    def on_task_start(self, ctx: PluginContext) -> PluginResult:
        return PluginResult.ok()

    def on_task_complete(self, ctx: PluginContext) -> PluginResult:
        return PluginResult.ok()

    def on_task_error(self, ctx: PluginContext) -> PluginResult:
        return PluginResult.ok()

    def on_pa_decision(self, ctx: PluginContext) -> PluginResult:
        return PluginResult.ok()
