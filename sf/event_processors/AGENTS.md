# sf/event_processors/ — Tool Event Enrichment

Extracts structured tags from Claude's `tool_use` events for OTEL telemetry.

## Interface

```python
class BaseToolUseEventProcessor(ABC):
    tool_name: str
    def process(self, event: dict) -> ToolEnrichment
```

`ToolEnrichment`: `tags` (`["shell", "git", "git:commit"]`), `attributes` (OTEL span attrs).

## Entry Points

- `process_tool_event(event)` — dispatches to registered processor by tool name.
- `register_processor(processor)` — adds custom processor.

Built-in processors: Bash, Read, Write, Edit, Glob, Grep, Task.
