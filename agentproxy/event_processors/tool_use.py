"""
Tool Use Event Processors
=========================

Processes tool_use events from Claude's stream-json output and extracts
structured enrichments for telemetry. Each processor handles a specific
tool type and emits labels + tags based on tool-specific parsing.

This is the PA->Claude observation path: PA sees Claude's stream-json
tool_use events and enriches telemetry with tool-specific context.

Tags are the primary classification mechanism -- each processor hardcodes
its built-in tags (e.g. ["shell", "git"], ["file_io", "ext:py"]).
Labels carry bounded-cardinality attributes suitable for Prometheus.

Architecture:
  - ToolEnrichment: Pydantic BaseModel (frozen, validated)
  - BaseToolUseEventProcessor: ABC for behavioral strategy objects
  - @register_processor: decorator-based registry (self-documenting)
  - BashCommandMatcher: data-driven sub-tool detection (extensible)
"""

import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, Field, field_validator


# --- Allowed label keys (bounded-cardinality for Prometheus) ---

ALLOWED_LABEL_KEYS: frozenset[str] = frozenset({
    "command_category", "subcommand",
    "file_extension", "operation", "domain",
    "subagent_type", "skill_name",
})


# --- Pydantic data models ---

class ToolEnrichment(BaseModel):
    """Enrichment data extracted from a tool_use event.

    Frozen (write-once) to prevent accidental mutation after creation.
    The labels validator silently strips non-allowed keys so that
    telemetry never crashes on unexpected label keys.
    """

    model_config = {"frozen": True}

    tool_name: str
    labels: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)

    @field_validator("labels")
    @classmethod
    def filter_label_keys(cls, v: dict[str, str]) -> dict[str, str]:
        """Silently strip non-allowed keys (telemetry must never crash)."""
        return {k: val for k, val in v.items() if k in ALLOWED_LABEL_KEYS}


class BashToolInput(BaseModel):
    """Validated input for Bash tool_use events."""

    model_config = {"extra": "ignore"}

    command: str = ""


class FileToolInput(BaseModel):
    """Validated input for file-oriented tool_use events.

    Claude's tools use different parameter names for file paths;
    this model normalises them via `resolved_path`.
    """

    model_config = {"extra": "ignore"}

    file_path: str = ""
    path: str = ""
    target_file: str = ""
    filename: str = ""
    notebook_path: str = ""

    @property
    def resolved_path(self) -> str:
        return (
            self.file_path or self.path or self.target_file
            or self.filename or self.notebook_path
        )


class WebToolInput(BaseModel):
    """Validated input for WebFetch tool_use events."""

    model_config = {"extra": "ignore"}

    url: str = ""


class BashCommandMatcher(BaseModel):
    """Configuration for detecting a CLI tool within a bash command string.

    Adding a new sub-tool (docker, npm, pip, make, etc.) is just adding
    a new BashCommandMatcher instance -- no code changes needed.
    """

    model_config = {"frozen": True}

    command_name: str
    pattern: str
    category: str
    tag_prefix: str
    known_subcommands: frozenset[str] = frozenset()


BASH_COMMAND_MATCHERS: list[BashCommandMatcher] = [
    BashCommandMatcher(
        command_name="git",
        pattern=r'\bgit\s+([a-z][-a-z]*)',
        category="git",
        tag_prefix="git",
        known_subcommands=frozenset({
            "commit", "push", "pull", "merge", "rebase", "checkout",
            "branch", "stash", "reset", "cherry-pick", "tag", "fetch",
            "clone", "init", "add", "diff", "log", "status",
        }),
    ),
    BashCommandMatcher(
        command_name="docker",
        pattern=r'\bdocker\s+([a-z][-a-z]*)',
        category="docker",
        tag_prefix="docker",
        known_subcommands=frozenset({
            "build", "run", "push", "pull", "compose", "exec",
            "stop", "rm", "ps", "images", "volume", "network",
        }),
    ),
    BashCommandMatcher(
        command_name="npm",
        pattern=r'\bnpm\s+([a-z][-a-z]*)',
        category="npm",
        tag_prefix="npm",
        known_subcommands=frozenset({
            "install", "run", "test", "build", "start", "publish", "init",
        }),
    ),
    BashCommandMatcher(
        command_name="pip",
        pattern=r'\bpip3?\s+([a-z][-a-z]*)',
        category="pip",
        tag_prefix="pip",
        known_subcommands=frozenset({"install", "uninstall", "freeze", "list"}),
    ),
    BashCommandMatcher(
        command_name="make",
        pattern=r'\bmake\s+([a-zA-Z][-a-zA-Z_]*)',
        category="make",
        tag_prefix="make",
    ),
    BashCommandMatcher(
        command_name="cargo",
        pattern=r'\bcargo\s+([a-z][-a-z]*)',
        category="cargo",
        tag_prefix="cargo",
        known_subcommands=frozenset({
            "build", "run", "test", "bench", "check", "clippy", "fmt",
        }),
    ),
]


# --- Processor base class and registry ---

_PROCESSOR_REGISTRY: dict[str, "BaseToolUseEventProcessor"] = {}


def register_processor(cls: type) -> type:
    """Class decorator that registers a processor for its declared tool_names.

    Raises ValueError on duplicate tool name registration.
    """
    instance = cls()
    for name in instance.tool_names:
        if name in _PROCESSOR_REGISTRY:
            raise ValueError(
                f"Duplicate processor registration for tool '{name}': "
                f"{type(_PROCESSOR_REGISTRY[name]).__name__} and {cls.__name__}"
            )
        _PROCESSOR_REGISTRY[name] = instance
    return cls


class BaseToolUseEventProcessor(ABC):
    """
    Base class for tool-specific enrichment of Claude's stream-json events.

    Subclasses override `process()` to extract structured data from
    tool_use input parameters. Returns a ToolEnrichment with labels
    suitable for telemetry emission and tags for classification.
    """

    tool_names: ClassVar[list[str]] = []

    @abstractmethod
    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        """
        Process a tool_use event and return enrichment data.

        Args:
            tool_name: The tool name from Claude's stream-json.
            tool_input: The tool input parameters dict.

        Returns:
            ToolEnrichment if enrichment was extracted, None otherwise.
        """
        ...


# --- Processor implementations ---

@register_processor
class BashToolProcessor(BaseToolUseEventProcessor):
    """
    Enriches Bash tool_use events with command classification.

    Uses data-driven BashCommandMatcher instances for sub-tool detection
    (git, docker, npm, pip, make, cargo). First match wins.
    """

    tool_names: ClassVar[list[str]] = ["Bash"]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        inp = BashToolInput.model_validate(tool_input)
        if not inp.command:
            return None

        labels: dict[str, str] = {}
        tags = ["shell"]

        for matcher in BASH_COMMAND_MATCHERS:
            match = re.search(matcher.pattern, inp.command)
            if match:
                labels["command_category"] = matcher.category
                labels["subcommand"] = match.group(1)
                tags.append(matcher.tag_prefix)
                tags.append(f"{matcher.tag_prefix}:{match.group(1)}")
                break
        else:
            first_token = inp.command.strip().split()[0] if inp.command.strip() else ""
            labels["command_category"] = first_token.rsplit("/", 1)[-1]

        return ToolEnrichment(tool_name=tool_name, labels=labels, tags=tags)


@register_processor
class WriteToolProcessor(BaseToolUseEventProcessor):
    """Enriches Write/Edit tool_use events with file metadata."""

    tool_names: ClassVar[list[str]] = [
        "Write", "Edit", "write_file", "edit_file",
        "str_replace_editor", "Create", "MultiEdit",
    ]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        inp = FileToolInput.model_validate(tool_input)
        file_path = inp.resolved_path
        if not file_path:
            return None

        labels: dict[str, str] = {"operation": tool_name.lower()}
        tags = ["file_io"]

        ext = _extract_extension(file_path)
        if ext:
            labels["file_extension"] = ext
            tags.append(f"ext:{ext}")

        return ToolEnrichment(tool_name=tool_name, labels=labels, tags=tags)


@register_processor
class ReadToolProcessor(BaseToolUseEventProcessor):
    """Enriches Read tool_use events with file metadata."""

    tool_names: ClassVar[list[str]] = ["Read"]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        inp = FileToolInput.model_validate(tool_input)
        file_path = inp.resolved_path
        if not file_path:
            return None

        labels: dict[str, str] = {"operation": "read"}
        tags = ["file_io"]

        ext = _extract_extension(file_path)
        if ext:
            labels["file_extension"] = ext
            tags.append(f"ext:{ext}")

        return ToolEnrichment(tool_name=tool_name, labels=labels, tags=tags)


@register_processor
class GlobToolProcessor(BaseToolUseEventProcessor):
    """Enriches Glob tool_use events. Extracts target extension from pattern."""

    tool_names: ClassVar[list[str]] = ["Glob"]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        pattern = tool_input.get("pattern", "")
        labels: dict[str, str] = {}
        tags = ["search", "glob"]

        if pattern:
            ext_match = re.search(r'\*\.(\w+)$', pattern)
            if ext_match:
                labels["file_extension"] = ext_match.group(1).lower()

        return ToolEnrichment(tool_name=tool_name, labels=labels, tags=tags)


@register_processor
class GrepToolProcessor(BaseToolUseEventProcessor):
    """Enriches Grep tool_use events. Extracts file type filter if present."""

    tool_names: ClassVar[list[str]] = ["Grep"]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        labels: dict[str, str] = {}
        tags = ["search", "grep"]

        file_type = tool_input.get("type", "")
        if file_type:
            labels["file_extension"] = file_type.lower()

        return ToolEnrichment(tool_name=tool_name, labels=labels, tags=tags)


@register_processor
class WebFetchToolProcessor(BaseToolUseEventProcessor):
    """Enriches WebFetch tool_use events. Extracts URL domain."""

    tool_names: ClassVar[list[str]] = ["WebFetch"]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        inp = WebToolInput.model_validate(tool_input)
        labels: dict[str, str] = {}
        tags = ["web", "fetch"]

        if inp.url:
            domain = _extract_domain(inp.url)
            if domain:
                labels["domain"] = domain

        return ToolEnrichment(tool_name=tool_name, labels=labels, tags=tags)


@register_processor
class WebSearchToolProcessor(BaseToolUseEventProcessor):
    """Enriches WebSearch tool_use events."""

    tool_names: ClassVar[list[str]] = ["WebSearch"]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        return ToolEnrichment(tool_name=tool_name, labels={}, tags=["web", "search"])


@register_processor
class NotebookEditToolProcessor(BaseToolUseEventProcessor):
    """Enriches NotebookEdit tool_use events with edit mode and cell type."""

    tool_names: ClassVar[list[str]] = ["NotebookEdit"]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        edit_mode = tool_input.get("edit_mode", "replace")
        labels: dict[str, str] = {"file_extension": "ipynb", "operation": edit_mode}
        tags = ["file_io", "ext:ipynb"]
        return ToolEnrichment(tool_name=tool_name, labels=labels, tags=tags)


@register_processor
class TaskToolProcessor(BaseToolUseEventProcessor):
    """Enriches Task (sub-agent) tool_use events. Extracts sub-agent type."""

    tool_names: ClassVar[list[str]] = ["Task"]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        labels: dict[str, str] = {}
        tags = ["agent"]

        subagent_type = tool_input.get("subagent_type", "")
        if subagent_type:
            labels["subagent_type"] = subagent_type
            tags.append(f"agent:{subagent_type}")

        return ToolEnrichment(tool_name=tool_name, labels=labels, tags=tags)


@register_processor
class SkillToolProcessor(BaseToolUseEventProcessor):
    """Enriches Skill tool_use events. Extracts skill name."""

    tool_names: ClassVar[list[str]] = ["Skill"]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        labels: dict[str, str] = {}
        tags = ["agent", "skill"]

        skill_name = tool_input.get("skill", "")
        if skill_name:
            labels["skill_name"] = skill_name
            tags.append(f"skill:{skill_name}")

        return ToolEnrichment(tool_name=tool_name, labels=labels, tags=tags)


@register_processor
class TodoWriteToolProcessor(BaseToolUseEventProcessor):
    """Enriches TodoWrite tool_use events."""

    tool_names: ClassVar[list[str]] = ["TodoWrite"]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        return ToolEnrichment(tool_name=tool_name, labels={}, tags=["planning", "todo"])


@register_processor
class AskUserQuestionToolProcessor(BaseToolUseEventProcessor):
    """Enriches AskUserQuestion tool_use events."""

    tool_names: ClassVar[list[str]] = ["AskUserQuestion"]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        return ToolEnrichment(tool_name=tool_name, labels={}, tags=["interaction", "question"])


@register_processor
class PlanModeToolProcessor(BaseToolUseEventProcessor):
    """Enriches EnterPlanMode / ExitPlanMode tool_use events."""

    tool_names: ClassVar[list[str]] = ["EnterPlanMode", "ExitPlanMode"]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        phase = "enter" if "Enter" in tool_name else "exit"
        labels: dict[str, str] = {"operation": phase}
        tags = ["planning", f"plan:{phase}"]
        return ToolEnrichment(tool_name=tool_name, labels=labels, tags=tags)


@register_processor
class ProcessToolProcessor(BaseToolUseEventProcessor):
    """Enriches KillShell / TaskOutput tool_use events."""

    tool_names: ClassVar[list[str]] = ["KillShell", "TaskOutput"]

    def process(self, tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
        operation = "kill" if tool_name == "KillShell" else "read_output"
        labels: dict[str, str] = {"operation": operation}
        tags = ["process"]
        return ToolEnrichment(tool_name=tool_name, labels=labels, tags=tags)


# --- Helpers ---

def _extract_extension(file_path: str) -> Optional[str]:
    """Extract lowercase file extension, or None if no extension."""
    basename = file_path.rsplit("/", 1)[-1]
    if "." in basename:
        return basename.rsplit(".", 1)[-1].lower()
    return None


def _extract_domain(url: str) -> Optional[str]:
    """Extract domain from a URL without importing urllib."""
    rest = url
    if "://" in rest:
        rest = rest.split("://", 1)[1]
    domain = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if ":" in domain:
        domain = domain.rsplit(":", 1)[0]
    return domain if domain else None


# --- Public API ---

def get_processor(tool_name: str) -> Optional[BaseToolUseEventProcessor]:
    """Get the processor for a given tool name, or None."""
    return _PROCESSOR_REGISTRY.get(tool_name)


def process_tool_event(tool_name: str, tool_input: dict[str, Any]) -> Optional[ToolEnrichment]:
    """
    Convenience: process a tool_use event through the appropriate processor.

    Args:
        tool_name: Tool name from Claude's stream-json.
        tool_input: Tool input parameters.

    Returns:
        ToolEnrichment if a processor matched and produced enrichment.
    """
    proc = get_processor(tool_name)
    if proc:
        return proc.process(tool_name, tool_input)
    return None
