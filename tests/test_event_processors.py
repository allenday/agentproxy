"""
Unit tests for event processors (tool_use).

Test categories:
  1. ToolEnrichment model — construction, defaults, immutability, label filtering
  2. Input models — BashToolInput, FileToolInput, WebToolInput
  3. BashCommandMatcher sub-tools — git, docker, npm, pip, make, cargo
  4. Per-processor — labels/tags extraction, edge cases
  5. Registry — get_processor dispatch, unknown tool, duplicate detection
  6. Integration — process_tool_event end-to-end
"""

import pytest
from pydantic import ValidationError

from sf.event_processors.tool_use import (
    ALLOWED_LABEL_KEYS,
    BASH_COMMAND_MATCHERS,
    BaseToolUseEventProcessor,
    BashCommandMatcher,
    BashToolInput,
    BashToolProcessor,
    FileToolInput,
    ToolEnrichment,
    WebToolInput,
    _PROCESSOR_REGISTRY,
    get_processor,
    process_tool_event,
    register_processor,
)


# ---- 1. ToolEnrichment model ----

class TestToolEnrichment:
    def test_construction_defaults(self):
        e = ToolEnrichment(tool_name="Bash")
        assert e.tool_name == "Bash"
        assert e.labels == {}
        assert e.tags == []

    def test_construction_with_labels_and_tags(self):
        e = ToolEnrichment(
            tool_name="Bash",
            labels={"command_category": "git", "subcommand": "push"},
            tags=["shell", "git"],
        )
        assert e.labels == {"command_category": "git", "subcommand": "push"}
        assert e.tags == ["shell", "git"]

    def test_immutability(self):
        e = ToolEnrichment(tool_name="Read", labels={"operation": "read"})
        with pytest.raises(ValidationError):
            e.tool_name = "Write"
        with pytest.raises(ValidationError):
            e.labels = {}

    def test_label_key_filtering_strips_unknown(self):
        e = ToolEnrichment(
            tool_name="Bash",
            labels={
                "command_category": "git",
                "dangerous_key": "should_be_stripped",
                "subcommand": "push",
            },
        )
        assert "dangerous_key" not in e.labels
        assert e.labels == {"command_category": "git", "subcommand": "push"}

    def test_label_key_filtering_all_allowed_keys_pass(self):
        all_labels = {k: "test" for k in ALLOWED_LABEL_KEYS}
        e = ToolEnrichment(tool_name="test", labels=all_labels)
        assert set(e.labels.keys()) == ALLOWED_LABEL_KEYS

    def test_label_key_filtering_empty_labels(self):
        e = ToolEnrichment(tool_name="test", labels={})
        assert e.labels == {}

    def test_model_dump_roundtrip(self):
        e = ToolEnrichment(
            tool_name="Bash",
            labels={"command_category": "git"},
            tags=["shell"],
        )
        data = e.model_dump()
        assert data == {
            "tool_name": "Bash",
            "labels": {"command_category": "git"},
            "tags": ["shell"],
        }
        e2 = ToolEnrichment.model_validate(data)
        assert e2 == e


# ---- 2. Input models ----

class TestBashToolInput:
    def test_extracts_command(self):
        inp = BashToolInput.model_validate({"command": "ls -la"})
        assert inp.command == "ls -la"

    def test_defaults_empty_command(self):
        inp = BashToolInput.model_validate({})
        assert inp.command == ""

    def test_ignores_extra_fields(self):
        inp = BashToolInput.model_validate({
            "command": "echo hello",
            "description": "Print hello",
            "timeout": 5000,
        })
        assert inp.command == "echo hello"
        assert not hasattr(inp, "description")


class TestFileToolInput:
    def test_resolved_path_priority(self):
        """file_path takes priority over path, target_file, filename, notebook_path."""
        inp = FileToolInput.model_validate({
            "file_path": "/a.py",
            "path": "/b.py",
            "target_file": "/c.py",
        })
        assert inp.resolved_path == "/a.py"

    def test_resolved_path_fallback_to_path(self):
        inp = FileToolInput.model_validate({"path": "/b.py"})
        assert inp.resolved_path == "/b.py"

    def test_resolved_path_fallback_to_target_file(self):
        inp = FileToolInput.model_validate({"target_file": "/c.py"})
        assert inp.resolved_path == "/c.py"

    def test_resolved_path_fallback_to_filename(self):
        inp = FileToolInput.model_validate({"filename": "/d.py"})
        assert inp.resolved_path == "/d.py"

    def test_resolved_path_fallback_to_notebook_path(self):
        inp = FileToolInput.model_validate({"notebook_path": "/e.ipynb"})
        assert inp.resolved_path == "/e.ipynb"

    def test_resolved_path_empty(self):
        inp = FileToolInput.model_validate({})
        assert inp.resolved_path == ""

    def test_ignores_extra_fields(self):
        inp = FileToolInput.model_validate({
            "file_path": "/x.py",
            "content": "hello",
            "old_string": "foo",
        })
        assert inp.resolved_path == "/x.py"


class TestWebToolInput:
    def test_extracts_url(self):
        inp = WebToolInput.model_validate({"url": "https://example.com"})
        assert inp.url == "https://example.com"

    def test_defaults_empty_url(self):
        inp = WebToolInput.model_validate({})
        assert inp.url == ""

    def test_ignores_extra_fields(self):
        inp = WebToolInput.model_validate({
            "url": "https://x.com",
            "prompt": "Summarize",
        })
        assert inp.url == "https://x.com"


# ---- 3. BashCommandMatcher sub-tools ----

class TestBashCommandMatcher:
    def test_matcher_frozen(self):
        m = BASH_COMMAND_MATCHERS[0]  # git
        with pytest.raises(ValidationError):
            m.command_name = "svn"

    def test_git_detection(self):
        result = process_tool_event("Bash", {"command": "git push origin main"})
        assert result is not None
        assert result.labels["command_category"] == "git"
        assert result.labels["subcommand"] == "push"
        assert "git" in result.tags
        assert "git:push" in result.tags

    def test_docker_detection(self):
        result = process_tool_event("Bash", {"command": "docker build -t myapp ."})
        assert result is not None
        assert result.labels["command_category"] == "docker"
        assert result.labels["subcommand"] == "build"
        assert "docker" in result.tags
        assert "docker:build" in result.tags

    def test_npm_detection(self):
        result = process_tool_event("Bash", {"command": "npm install express"})
        assert result is not None
        assert result.labels["command_category"] == "npm"
        assert result.labels["subcommand"] == "install"
        assert "npm" in result.tags

    def test_pip_detection(self):
        result = process_tool_event("Bash", {"command": "pip install requests"})
        assert result is not None
        assert result.labels["command_category"] == "pip"
        assert result.labels["subcommand"] == "install"
        assert "pip" in result.tags

    def test_pip3_detection(self):
        result = process_tool_event("Bash", {"command": "pip3 install flask"})
        assert result is not None
        assert result.labels["command_category"] == "pip"
        assert result.labels["subcommand"] == "install"

    def test_make_detection(self):
        result = process_tool_event("Bash", {"command": "make build"})
        assert result is not None
        assert result.labels["command_category"] == "make"
        assert result.labels["subcommand"] == "build"
        assert "make" in result.tags

    def test_cargo_detection(self):
        result = process_tool_event("Bash", {"command": "cargo test --release"})
        assert result is not None
        assert result.labels["command_category"] == "cargo"
        assert result.labels["subcommand"] == "test"
        assert "cargo" in result.tags

    def test_first_match_wins(self):
        """git matcher comes before docker, so 'git ...' should match git."""
        result = process_tool_event("Bash", {"command": "git clone https://github.com/x"})
        assert result.labels["command_category"] == "git"

    def test_fallback_to_raw_command(self):
        result = process_tool_event("Bash", {"command": "ls -la /tmp"})
        assert result is not None
        assert result.labels["command_category"] == "ls"
        assert "subcommand" not in result.labels
        assert result.tags == ["shell"]

    def test_fallback_strips_path(self):
        result = process_tool_event("Bash", {"command": "/usr/bin/python3 script.py"})
        assert result.labels["command_category"] == "python3"

    def test_custom_matcher_extensibility(self):
        """Third-party code can append a new matcher."""
        custom = BashCommandMatcher(
            command_name="kubectl",
            pattern=r'\bkubectl\s+([a-z][-a-z]*)',
            category="kubectl",
            tag_prefix="kubectl",
        )
        BASH_COMMAND_MATCHERS.append(custom)
        try:
            result = process_tool_event("Bash", {"command": "kubectl get pods"})
            assert result.labels["command_category"] == "kubectl"
            assert result.labels["subcommand"] == "get"
            assert "kubectl" in result.tags
        finally:
            BASH_COMMAND_MATCHERS.remove(custom)


# ---- 4. Per-processor tests ----

class TestBashToolProcessor:
    def test_empty_command_returns_none(self):
        assert process_tool_event("Bash", {"command": ""}) is None

    def test_missing_command_returns_none(self):
        assert process_tool_event("Bash", {}) is None

    def test_shell_tag_always_present(self):
        result = process_tool_event("Bash", {"command": "echo hello"})
        assert "shell" in result.tags


class TestWriteToolProcessor:
    def test_write_python_file(self):
        result = process_tool_event("Write", {"file_path": "/src/app.py", "content": "x=1"})
        assert result.labels["operation"] == "write"
        assert result.labels["file_extension"] == "py"
        assert "file_io" in result.tags
        assert "ext:py" in result.tags

    def test_edit_typescript(self):
        result = process_tool_event("Edit", {"file_path": "/src/index.ts", "old_string": "a", "new_string": "b"})
        assert result.labels["operation"] == "edit"
        assert result.labels["file_extension"] == "ts"

    def test_no_file_path_returns_none(self):
        assert process_tool_event("Write", {"content": "hello"}) is None

    def test_no_extension(self):
        result = process_tool_event("Write", {"file_path": "/Makefile"})
        assert "file_extension" not in result.labels

    def test_str_replace_editor(self):
        result = process_tool_event("str_replace_editor", {"target_file": "/a.rs"})
        assert result.labels["operation"] == "str_replace_editor"
        assert result.labels["file_extension"] == "rs"


class TestReadToolProcessor:
    def test_read_python(self):
        result = process_tool_event("Read", {"file_path": "/src/main.py"})
        assert result.labels["operation"] == "read"
        assert result.labels["file_extension"] == "py"
        assert "file_io" in result.tags

    def test_read_empty_returns_none(self):
        assert process_tool_event("Read", {}) is None


class TestGlobToolProcessor:
    def test_glob_with_extension(self):
        result = process_tool_event("Glob", {"pattern": "**/*.ts"})
        assert result.labels["file_extension"] == "ts"
        assert "search" in result.tags
        assert "glob" in result.tags

    def test_glob_no_extension(self):
        result = process_tool_event("Glob", {"pattern": "**/Makefile"})
        assert "file_extension" not in result.labels

    def test_glob_empty_pattern(self):
        result = process_tool_event("Glob", {"pattern": ""})
        assert result is not None
        assert result.labels == {}


class TestGrepToolProcessor:
    def test_grep_with_type(self):
        result = process_tool_event("Grep", {"pattern": "TODO", "type": "py"})
        assert result.labels["file_extension"] == "py"
        assert "search" in result.tags
        assert "grep" in result.tags

    def test_grep_no_type(self):
        result = process_tool_event("Grep", {"pattern": "error"})
        assert "file_extension" not in result.labels


class TestWebFetchToolProcessor:
    def test_webfetch_extracts_domain(self):
        result = process_tool_event("WebFetch", {"url": "https://docs.python.org/3/library/re.html"})
        assert result.labels["domain"] == "docs.python.org"
        assert "web" in result.tags
        assert "fetch" in result.tags

    def test_webfetch_empty_url(self):
        result = process_tool_event("WebFetch", {"url": ""})
        assert "domain" not in result.labels

    def test_webfetch_strips_port(self):
        result = process_tool_event("WebFetch", {"url": "http://localhost:8080/api"})
        assert result.labels["domain"] == "localhost"


class TestWebSearchToolProcessor:
    def test_websearch_tags(self):
        result = process_tool_event("WebSearch", {"query": "python pydantic v2"})
        assert result.tags == ["web", "search"]
        assert result.labels == {}


class TestNotebookEditToolProcessor:
    def test_notebook_default_edit_mode(self):
        result = process_tool_event("NotebookEdit", {"notebook_path": "/nb.ipynb", "new_source": "x"})
        assert result.labels["file_extension"] == "ipynb"
        assert result.labels["operation"] == "replace"

    def test_notebook_insert_mode(self):
        result = process_tool_event("NotebookEdit", {"edit_mode": "insert", "new_source": "x"})
        assert result.labels["operation"] == "insert"


class TestTaskToolProcessor:
    def test_task_with_subagent(self):
        result = process_tool_event("Task", {"subagent_type": "Explore", "prompt": "find files"})
        assert result.labels["subagent_type"] == "Explore"
        assert "agent" in result.tags
        assert "agent:Explore" in result.tags

    def test_task_without_subagent(self):
        result = process_tool_event("Task", {"prompt": "do stuff"})
        assert "subagent_type" not in result.labels


class TestSkillToolProcessor:
    def test_skill_with_name(self):
        result = process_tool_event("Skill", {"skill": "commit"})
        assert result.labels["skill_name"] == "commit"
        assert "skill:commit" in result.tags

    def test_skill_without_name(self):
        result = process_tool_event("Skill", {})
        assert "skill_name" not in result.labels


class TestTodoWriteToolProcessor:
    def test_todo_tags(self):
        result = process_tool_event("TodoWrite", {"todos": [{"id": "1", "content": "x"}]})
        assert result.tags == ["planning", "todo"]


class TestAskUserQuestionToolProcessor:
    def test_question_tags(self):
        result = process_tool_event("AskUserQuestion", {"question": "Which approach?"})
        assert result.tags == ["interaction", "question"]


class TestPlanModeToolProcessor:
    def test_enter_plan_mode(self):
        result = process_tool_event("EnterPlanMode", {})
        assert result.labels["operation"] == "enter"
        assert "plan:enter" in result.tags

    def test_exit_plan_mode(self):
        result = process_tool_event("ExitPlanMode", {})
        assert result.labels["operation"] == "exit"
        assert "plan:exit" in result.tags


class TestProcessToolProcessor:
    def test_kill_shell(self):
        result = process_tool_event("KillShell", {})
        assert result.labels["operation"] == "kill"
        assert "process" in result.tags

    def test_task_output(self):
        result = process_tool_event("TaskOutput", {})
        assert result.labels["operation"] == "read_output"


# ---- 5. Registry ----

class TestRegistry:
    def test_get_processor_returns_correct_type(self):
        proc = get_processor("Bash")
        assert isinstance(proc, BashToolProcessor)

    def test_get_processor_unknown_returns_none(self):
        assert get_processor("UnknownTool") is None

    def test_all_expected_tools_registered(self):
        expected_tools = {
            "Bash", "Write", "Edit", "write_file", "edit_file",
            "str_replace_editor", "Create", "MultiEdit",
            "Read", "Glob", "Grep", "WebFetch", "WebSearch",
            "NotebookEdit", "Task", "Skill", "TodoWrite",
            "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
            "KillShell", "TaskOutput",
        }
        assert expected_tools.issubset(set(_PROCESSOR_REGISTRY.keys()))

    def test_duplicate_registration_raises(self):
        with pytest.raises(ValueError, match="Duplicate"):
            @register_processor
            class DuplicateBash(BaseToolUseEventProcessor):
                tool_names = ["Bash"]

                def process(self, tool_name, tool_input):
                    return None

    def test_abc_prevents_missing_process(self):
        """Subclass without process() cannot be instantiated."""
        with pytest.raises(TypeError):
            class BadProcessor(BaseToolUseEventProcessor):
                tool_names = ["Bad"]

            BadProcessor()


# ---- 6. Integration — process_tool_event end-to-end ----

class TestProcessToolEventIntegration:
    def test_unknown_tool_returns_none(self):
        assert process_tool_event("SomethingNew", {"data": 1}) is None

    def test_bash_git_e2e(self):
        result = process_tool_event("Bash", {"command": "git commit -m 'fix'"})
        assert result.tool_name == "Bash"
        assert result.labels["command_category"] == "git"
        assert result.labels["subcommand"] == "commit"
        assert "shell" in result.tags
        assert "git" in result.tags
        assert "git:commit" in result.tags

    def test_write_e2e(self):
        result = process_tool_event("Write", {
            "file_path": "/src/utils.ts",
            "content": "export const x = 1;",
        })
        assert result.tool_name == "Write"
        assert result.labels["operation"] == "write"
        assert result.labels["file_extension"] == "ts"

    def test_enrichment_labels_are_pre_filtered(self):
        """Labels returned from process_tool_event never contain disallowed keys."""
        result = process_tool_event("Bash", {"command": "git status"})
        for key in result.labels:
            assert key in ALLOWED_LABEL_KEYS

    def test_enrichment_is_frozen(self):
        result = process_tool_event("Bash", {"command": "git log"})
        with pytest.raises(ValidationError):
            result.tool_name = "hacked"
