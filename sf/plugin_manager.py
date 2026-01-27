"""
PluginManager: discovery, loading, and hook dispatch for SF plugins.

Plugins are loaded from:
1. Built-in plugins (OTEL plugin when SF_ENABLE_TELEMETRY=1)
2. SF_PLUGINS_DIR directory (glob *.py, skip _-prefixed files)
3. SF_PLUGINS comma-separated module paths
"""

import importlib
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .plugins.base import PluginContext, PluginHookPhase, PluginResult, SFPlugin

logger = logging.getLogger(__name__)


class PluginManager:
    """Discovers, loads, and dispatches hooks to SF plugins."""

    def __init__(self) -> None:
        self.plugins: List[SFPlugin] = []
        self._load_plugins()

    def _load_plugins(self) -> None:
        """Load plugins from all configured sources."""
        self._load_builtin_plugins()
        self._load_directory_plugins()
        self._load_module_plugins()

    def _load_builtin_plugins(self) -> None:
        """Load built-in plugins based on environment config."""
        if os.getenv("SF_ENABLE_TELEMETRY", "0") == "1":
            try:
                from .plugins.otel_plugin import OTELPlugin

                self.plugins.append(OTELPlugin())
                logger.info("Loaded built-in plugin: otel")
            except Exception as e:
                logger.warning("Failed to load OTEL plugin: %s", e)

    def _load_directory_plugins(self) -> None:
        """Load plugins from SF_PLUGINS_DIR directory."""
        plugins_dir = os.getenv("SF_PLUGINS_DIR")
        if not plugins_dir:
            return

        dir_path = Path(plugins_dir)
        if not dir_path.is_dir():
            logger.warning("SF_PLUGINS_DIR=%s is not a directory", plugins_dir)
            return

        for py_file in sorted(dir_path.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                plugin = self._load_plugin_from_file(py_file)
                if plugin:
                    self.plugins.append(plugin)
                    logger.info("Loaded plugin from file: %s", py_file.name)
            except Exception as e:
                logger.warning("Failed to load plugin from %s: %s", py_file, e)

    def _load_plugin_from_file(self, path: Path) -> Optional[SFPlugin]:
        """Load an SFPlugin subclass from a Python file."""
        spec = importlib.util.spec_from_file_location(path.stem, str(path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find the first SFPlugin subclass in the module
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, SFPlugin)
                and attr is not SFPlugin
            ):
                return attr()
        return None

    def _load_module_plugins(self) -> None:
        """Load plugins from SF_PLUGINS comma-separated module paths."""
        plugins_str = os.getenv("SF_PLUGINS")
        if not plugins_str:
            return

        for module_path in plugins_str.split(","):
            module_path = module_path.strip()
            if not module_path:
                continue
            try:
                plugin = self._load_plugin_from_module(module_path)
                if plugin:
                    self.plugins.append(plugin)
                    logger.info("Loaded plugin from module: %s", module_path)
            except Exception as e:
                logger.warning("Failed to load plugin from module %s: %s", module_path, e)

    def _load_plugin_from_module(self, module_path: str) -> Optional[SFPlugin]:
        """Load an SFPlugin subclass from a dotted module path."""
        module = importlib.import_module(module_path)
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, SFPlugin)
                and attr is not SFPlugin
            ):
                return attr()
        return None

    def initialize_plugins(self, pa: Any) -> None:
        """Call on_init(pa) on all loaded plugins."""
        for plugin in self.plugins:
            try:
                plugin.on_init(pa)
                logger.info("Initialized plugin: %s v%s", plugin.name, plugin.version)
            except Exception as e:
                logger.warning("Plugin %s failed on_init: %s", plugin.name, e)

    def trigger_hook(self, phase: PluginHookPhase, **context_data: Any) -> List[PluginResult]:
        """Trigger a hook phase on all plugins that support it.

        Short-circuits on the first block result.
        Plugin errors are caught and logged; they never crash PA.

        Returns:
            List of PluginResult from each plugin that handled the hook.
        """
        ctx = PluginContext(phase=phase, data=context_data)
        results: List[PluginResult] = []

        for plugin in self.plugins:
            if not plugin.supports_hook(phase):
                continue
            try:
                result = plugin.execute_hook(ctx)
                results.append(result)
                if result.action == "block":
                    logger.info(
                        "Plugin %s blocked %s: %s",
                        plugin.name, phase.value, result.message,
                    )
                    break  # Short-circuit on block
            except Exception as e:
                logger.warning(
                    "Plugin %s error during %s: %s",
                    plugin.name, phase.value, e,
                )
                # Plugin errors never crash PA — continue to next plugin

        return results

    @staticmethod
    def check_blocked(results: List[PluginResult]) -> Tuple[bool, Optional[str]]:
        """Check if any result in the list is a block.

        Returns:
            (is_blocked, block_message) tuple.
        """
        for result in results:
            if result.action == "block":
                return True, result.message
        return False, None
