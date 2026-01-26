"""
File Change Tracker
===================

Tracks files modified by Claude during execution.
Parses Claude's streaming JSON output to detect file operations.
"""

from typing import Any, Dict, List

from .gemini_client import GeminiClient


class FileChangeTracker:
    """
    Tracks files modified by Claude during execution.
    
    Parses Claude's streaming JSON output to detect file write/edit operations
    and maintains a list of changed files for PA to review.
    
    Usage:
        tracker = FileChangeTracker("./project")
        for event in claude_stream:
            tracker.process_event(event)
        print(tracker.get_changed_files())
    """
    
    # Tool names that modify files (various naming conventions)
    FILE_MODIFY_TOOLS = {
        "write_file", "Write", "write",
        "edit_file", "Edit", "edit",
        "str_replace_editor", "str_replace",
        "create_file", "Create",
        "insert_lines", "insert",
        "MultiEdit", "multi_edit",
    }
    
    def __init__(self, working_dir: str = ".") -> None:
        """
        Initialize tracker.
        
        Args:
            working_dir: Working directory for relative path resolution.
        """
        self.working_dir = working_dir
        self._changed_files: Dict[str, str] = {}  # path -> operation type
        self._is_done = False
        self._done_message = ""
    
    def process_event(self, event_data: Dict[str, Any]) -> None:
        """
        Process a streaming JSON event from Claude to detect file changes.
        
        Args:
            event_data: Parsed JSON event from Claude's output.
        """
        event_type = event_data.get("type", "")
        
        # Check for tool use events in assistant messages
        if event_type == "assistant":
            message = event_data.get("message", {})
            for item in message.get("content", []):
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    self._process_tool_use(item)
        
        # Check for result/completion events
        if event_type == "result":
            result_text = event_data.get("result", "")
            subtype = event_data.get("subtype", "")
            if subtype == "success" or self._check_completion(result_text):
                self._is_done = True
                self._done_message = result_text
    
    def _process_tool_use(self, tool_data: Dict[str, Any]) -> None:
        """
        Extract file path from a tool use event.
        
        Args:
            tool_data: Tool use data containing name and input.
        """
        tool_name = tool_data.get("name", "")
        tool_input = tool_data.get("input", {})
        
        if tool_name in self.FILE_MODIFY_TOOLS:
            # Try various parameter names for file path
            file_path = (
                tool_input.get("file_path") or
                tool_input.get("path") or
                tool_input.get("target_file") or
                tool_input.get("filename") or
                ""
            )
            if file_path:
                self._changed_files[file_path] = tool_name
    
    def _check_completion(self, text: str) -> bool:
        """
        Use Gemini to analyze if Claude's output indicates task completion.
        
        Args:
            text: Result text to analyze.
            
        Returns:
            True if text indicates completion.
        """
        if not text or len(text.strip()) < 10:
            return False
        
        try:
            gemini = GeminiClient()
            return gemini.analyze_completion(text)
        except Exception:
            return False
    
    def get_changed_files(self) -> List[str]:
        """
        Get list of files that were modified.
        
        Returns:
            List of file paths.
        """
        return list(self._changed_files.keys())
    
    def get_changes_summary(self) -> str:
        """
        Get a human-readable summary of all file changes.

        Returns:
            Summary string.
        """
        if not self._changed_files:
            return "No files were modified."

        lines = ["Files modified by Claude:"]
        for path, operation in self._changed_files.items():
            lines.append(f"  - {path} ({operation})")
        return "\n".join(lines)

    def get_code_changes(self, files: list[str] | None = None) -> tuple[int, int]:
        """
        Get lines added and removed using git diff.

        Args:
            files: Explicit list of file paths to diff. When ``None``,
                falls back to ``self._changed_files``.

        Returns:
            Tuple of (lines_added, lines_removed)
        """
        changed = files or list(self._changed_files.keys())
        if not changed:
            return (0, 0)

        try:
            import subprocess

            cwd = self.working_dir

            # Stage changed files so new (untracked) files appear in diff.
            # Uses -N (intent-to-add) to avoid modifying file content in index.
            subprocess.run(
                ["git", "add", "-N", "--"] + changed,
                cwd=cwd, capture_output=True, timeout=5,
            )

            # Diff against HEAD to get lines added/removed
            result = subprocess.run(
                ["git", "diff", "--numstat", "HEAD", "--"] + changed,
                cwd=cwd, capture_output=True, text=True, timeout=5,
            )

            lines_added = 0
            lines_removed = 0

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    lines_added += int(parts[0])
                    lines_removed += int(parts[1])

            return (lines_added, lines_removed)

        except Exception:
            # If git fails or no git repo, return 0
            return (0, 0)

    @property
    def is_done(self) -> bool:
        """Return True if Claude indicated task completion."""
        return self._is_done
    
    @property
    def done_message(self) -> str:
        """Return Claude's completion message."""
        return self._done_message
    
    def reset(self) -> None:
        """Reset tracker state for a new task iteration."""
        self._changed_files.clear()
        self._is_done = False
        self._done_message = ""
