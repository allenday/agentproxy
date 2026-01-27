"""
Comprehensive tests for the SF Plugin Architecture.

Test plugins:
  - LoggingPlugin: records all hook calls
  - BlockingPlugin: blocks tasks containing "forbidden"
  - ErrorPlugin: raises RuntimeError

Test classes:
  - TestPluginResult: ok, block, modify
  - TestPluginContext: phase and data
  - TestSFPlugin: supports_hook, execute_hook dispatch
  - TestPluginManager: loading, trigger_hook, blocking, error resilience
"""

import os
from typing import Any, List
from unittest.mock import patch

import pytest

from sf.plugins.base import (
    PluginContext,
    PluginHookPhase,
    PluginResult,
    SFPlugin,
)
from sf.plugin_manager import PluginManager


# ---------------------------------------------------------------------------
# Test plugin fixtures
# ---------------------------------------------------------------------------


class LoggingPlugin(SFPlugin):
    """Records all hook calls for assertion."""

    def __init__(self):
        self.calls: List[PluginContext] = []

    @property
    def name(self) -> str:
        return "logging"

    def on_task_start(self, ctx: PluginContext) -> PluginResult:
        self.calls.append(ctx)
        return PluginResult.ok()

    def on_task_complete(self, ctx: PluginContext) -> PluginResult:
        self.calls.append(ctx)
        return PluginResult.ok()

    def on_task_error(self, ctx: PluginContext) -> PluginResult:
        self.calls.append(ctx)
        return PluginResult.ok()

    def on_pa_decision(self, ctx: PluginContext) -> PluginResult:
        self.calls.append(ctx)
        return PluginResult.ok()


class BlockingPlugin(SFPlugin):
    """Blocks tasks whose description contains 'forbidden'."""

    @property
    def name(self) -> str:
        return "blocker"

    def on_task_start(self, ctx: PluginContext) -> PluginResult:
        task = ctx.data.get("task", "")
        if "forbidden" in task:
            return PluginResult.block("Task contains forbidden content")
        return PluginResult.ok()


class ErrorPlugin(SFPlugin):
    """Always raises RuntimeError inside hook handlers."""

    @property
    def name(self) -> str:
        return "error"

    def on_task_start(self, ctx: PluginContext) -> PluginResult:
        raise RuntimeError("plugin exploded")


class DecisionOnlyPlugin(SFPlugin):
    """Only overrides on_pa_decision — used to test supports_hook."""

    def __init__(self):
        self.decisions: List[PluginContext] = []

    @property
    def name(self) -> str:
        return "decision-only"

    def on_pa_decision(self, ctx: PluginContext) -> PluginResult:
        self.decisions.append(ctx)
        return PluginResult.ok()


# ---------------------------------------------------------------------------
# TestPluginResult
# ---------------------------------------------------------------------------


class TestPluginResult:
    def test_ok(self):
        r = PluginResult.ok()
        assert r.action == "continue"
        assert r.message is None
        assert r.data == {}

    def test_block(self):
        r = PluginResult.block("not allowed")
        assert r.action == "block"
        assert r.message == "not allowed"
        assert r.data == {}

    def test_modify(self):
        r = PluginResult.modify({"key": "value"})
        assert r.action == "modify"
        assert r.message is None
        assert r.data == {"key": "value"}

    def test_frozen(self):
        r = PluginResult.ok()
        with pytest.raises(AttributeError):
            r.action = "block"


# ---------------------------------------------------------------------------
# TestPluginContext
# ---------------------------------------------------------------------------


class TestPluginContext:
    def test_phase_and_data(self):
        ctx = PluginContext(
            phase=PluginHookPhase.ON_TASK_START,
            data={"task": "build it"},
        )
        assert ctx.phase == PluginHookPhase.ON_TASK_START
        assert ctx.data["task"] == "build it"

    def test_default_data(self):
        ctx = PluginContext(phase=PluginHookPhase.ON_TASK_ERROR)
        assert ctx.data == {}

    def test_frozen(self):
        ctx = PluginContext(phase=PluginHookPhase.ON_TASK_START)
        with pytest.raises(AttributeError):
            ctx.phase = PluginHookPhase.ON_TASK_ERROR


# ---------------------------------------------------------------------------
# TestSFPlugin
# ---------------------------------------------------------------------------


class TestSFPlugin:
    def test_supports_hook_overridden(self):
        plugin = LoggingPlugin()
        assert plugin.supports_hook(PluginHookPhase.ON_TASK_START) is True
        assert plugin.supports_hook(PluginHookPhase.ON_TASK_COMPLETE) is True
        assert plugin.supports_hook(PluginHookPhase.ON_TASK_ERROR) is True
        assert plugin.supports_hook(PluginHookPhase.ON_PA_DECISION) is True

    def test_supports_hook_not_overridden(self):
        plugin = BlockingPlugin()
        assert plugin.supports_hook(PluginHookPhase.ON_TASK_START) is True
        # BlockingPlugin only overrides on_task_start
        assert plugin.supports_hook(PluginHookPhase.ON_TASK_COMPLETE) is False
        assert plugin.supports_hook(PluginHookPhase.ON_TASK_ERROR) is False
        assert plugin.supports_hook(PluginHookPhase.ON_PA_DECISION) is False

    def test_supports_hook_aspirational(self):
        plugin = LoggingPlugin()
        # Aspirational hooks are not wired — supports_hook returns False
        assert plugin.supports_hook(PluginHookPhase.ON_FUNCTION_PRE) is False
        assert plugin.supports_hook(PluginHookPhase.ON_CLAUDE_START) is False

    def test_supports_hook_selective(self):
        plugin = DecisionOnlyPlugin()
        assert plugin.supports_hook(PluginHookPhase.ON_PA_DECISION) is True
        assert plugin.supports_hook(PluginHookPhase.ON_TASK_START) is False

    def test_execute_hook_dispatch(self):
        plugin = LoggingPlugin()
        ctx = PluginContext(
            phase=PluginHookPhase.ON_TASK_START,
            data={"task": "test"},
        )
        result = plugin.execute_hook(ctx)
        assert result.action == "continue"
        assert len(plugin.calls) == 1
        assert plugin.calls[0].phase == PluginHookPhase.ON_TASK_START

    def test_execute_hook_unhandled_phase(self):
        plugin = LoggingPlugin()
        ctx = PluginContext(phase=PluginHookPhase.ON_FILE_CHANGE)
        result = plugin.execute_hook(ctx)
        assert result.action == "continue"
        # No call recorded — aspirational hook is not dispatched
        assert len(plugin.calls) == 0

    def test_default_version(self):
        plugin = LoggingPlugin()
        assert plugin.version == "0.1.0"

    def test_on_init_default_noop(self):
        plugin = LoggingPlugin()
        # Should not raise
        plugin.on_init(object())


# ---------------------------------------------------------------------------
# TestPluginManager
# ---------------------------------------------------------------------------


class TestPluginManager:
    def test_no_plugins_by_default(self):
        """Without env vars, zero plugins load."""
        with patch.dict(os.environ, {}, clear=True):
            # Need to ensure SF_ENABLE_TELEMETRY is absent
            env = os.environ.copy()
            env.pop("SF_ENABLE_TELEMETRY", None)
            env.pop("SF_PLUGINS_DIR", None)
            env.pop("SF_PLUGINS", None)
            with patch.dict(os.environ, env, clear=True):
                mgr = PluginManager()
                assert len(mgr.plugins) == 0

    def test_trigger_hook_no_plugins(self):
        with patch.dict(os.environ, {}, clear=True):
            mgr = PluginManager()
            results = mgr.trigger_hook(PluginHookPhase.ON_TASK_START, task="hello")
            assert results == []

    def test_trigger_hook_returns_results(self):
        mgr = PluginManager()
        mgr.plugins = [LoggingPlugin()]
        results = mgr.trigger_hook(
            PluginHookPhase.ON_TASK_START, task="build app",
        )
        assert len(results) == 1
        assert results[0].action == "continue"

    def test_trigger_hook_block_short_circuits(self):
        """First block stops further plugin execution."""
        logging_plugin = LoggingPlugin()
        blocking_plugin = BlockingPlugin()
        after_plugin = LoggingPlugin()

        mgr = PluginManager()
        mgr.plugins = [logging_plugin, blocking_plugin, after_plugin]

        results = mgr.trigger_hook(
            PluginHookPhase.ON_TASK_START, task="do the forbidden thing",
        )
        # logging_plugin ran (continue), blocking_plugin ran (block), after_plugin skipped
        assert len(results) == 2
        assert results[0].action == "continue"
        assert results[1].action == "block"
        assert results[1].message == "Task contains forbidden content"
        # after_plugin should have zero calls
        assert len(after_plugin.calls) == 0

    def test_trigger_hook_error_resilience(self):
        """Plugin errors are caught; PA continues."""
        error_plugin = ErrorPlugin()
        logging_plugin = LoggingPlugin()

        mgr = PluginManager()
        mgr.plugins = [error_plugin, logging_plugin]

        # Should NOT raise despite ErrorPlugin exploding
        results = mgr.trigger_hook(PluginHookPhase.ON_TASK_START, task="test")
        # ErrorPlugin errored (no result), LoggingPlugin succeeded
        assert len(results) == 1
        assert results[0].action == "continue"
        assert len(logging_plugin.calls) == 1

    def test_trigger_hook_skips_unsupported(self):
        """Plugins that don't support a phase are skipped."""
        decision_plugin = DecisionOnlyPlugin()
        mgr = PluginManager()
        mgr.plugins = [decision_plugin]

        # ON_TASK_START — not supported by DecisionOnlyPlugin
        results = mgr.trigger_hook(PluginHookPhase.ON_TASK_START, task="test")
        assert results == []
        assert len(decision_plugin.decisions) == 0

        # ON_PA_DECISION — supported
        results = mgr.trigger_hook(
            PluginHookPhase.ON_PA_DECISION,
            decision="continue",
            function="synthesize_instruction",
            iteration=3,
        )
        assert len(results) == 1
        assert len(decision_plugin.decisions) == 1

    def test_check_blocked_no_blocks(self):
        results = [PluginResult.ok(), PluginResult.ok()]
        blocked, msg = PluginManager.check_blocked(results)
        assert blocked is False
        assert msg is None

    def test_check_blocked_with_block(self):
        results = [PluginResult.ok(), PluginResult.block("nope")]
        blocked, msg = PluginManager.check_blocked(results)
        assert blocked is True
        assert msg == "nope"

    def test_check_blocked_empty(self):
        blocked, msg = PluginManager.check_blocked([])
        assert blocked is False
        assert msg is None

    def test_initialize_plugins(self):
        """on_init is called on all plugins."""

        class InitTracker(SFPlugin):
            def __init__(self):
                self.init_pa = None

            @property
            def name(self):
                return "init-tracker"

            def on_init(self, pa):
                self.init_pa = pa

        tracker = InitTracker()
        mgr = PluginManager()
        mgr.plugins = [tracker]

        sentinel = object()
        mgr.initialize_plugins(sentinel)
        assert tracker.init_pa is sentinel

    def test_initialize_plugins_error_resilience(self):
        """on_init errors are caught; other plugins still initialize."""

        class BadInitPlugin(SFPlugin):
            @property
            def name(self):
                return "bad-init"

            def on_init(self, pa):
                raise ValueError("init failed")

        class GoodPlugin(SFPlugin):
            def __init__(self):
                self.initialized = False

            @property
            def name(self):
                return "good"

            def on_init(self, pa):
                self.initialized = True

        bad = BadInitPlugin()
        good = GoodPlugin()
        mgr = PluginManager()
        mgr.plugins = [bad, good]

        mgr.initialize_plugins(object())
        assert good.initialized is True

    def test_trigger_hook_passes_context_data(self):
        """Verify that context_data kwargs are available in ctx.data."""
        plugin = LoggingPlugin()
        mgr = PluginManager()
        mgr.plugins = [plugin]

        mgr.trigger_hook(
            PluginHookPhase.ON_TASK_ERROR,
            task="build it",
            error="something broke",
        )

        assert len(plugin.calls) == 1
        ctx = plugin.calls[0]
        assert ctx.phase == PluginHookPhase.ON_TASK_ERROR
        assert ctx.data["task"] == "build it"
        assert ctx.data["error"] == "something broke"

    def test_multiple_hooks_in_sequence(self):
        """Plugin accumulates state across multiple hook calls."""
        plugin = LoggingPlugin()
        mgr = PluginManager()
        mgr.plugins = [plugin]

        mgr.trigger_hook(PluginHookPhase.ON_TASK_START, task="hello")
        mgr.trigger_hook(PluginHookPhase.ON_PA_DECISION, decision="continue")
        mgr.trigger_hook(PluginHookPhase.ON_TASK_COMPLETE, status="completed")

        assert len(plugin.calls) == 3
        assert plugin.calls[0].phase == PluginHookPhase.ON_TASK_START
        assert plugin.calls[1].phase == PluginHookPhase.ON_PA_DECISION
        assert plugin.calls[2].phase == PluginHookPhase.ON_TASK_COMPLETE
