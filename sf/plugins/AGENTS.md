# sf/plugins/ — Plugin System

Lifecycle hooks for PA operations.

## Interface

```python
class SFPlugin(ABC):
    name: str
    def on_hook(self, phase: PluginHookPhase, context: PluginContext) -> PluginResult
```

## Phases

`ON_TASK_START`, `ON_TASK_END`, `ON_ITERATION_START`, `ON_ITERATION_END`, `ON_FUNCTION_PRE`, `ON_FUNCTION_POST`, `ON_ERROR`

## Built-in

`OTELPlugin` (`otel_plugin.py`) — wires telemetry spans/metrics into PA lifecycle.

## Wiring

`PluginManager.initialize_plugins(pa)` auto-loads plugins. Connected to PA via `_plugin_manager` and to `FunctionExecutor` for pre/post function hooks.
