import os
import subprocess
import json
from typing import List

from ..base import LLMProvider, register_provider
from ..types import LLMRequest, LLMResult, LLMToolCall


@register_provider("claude_cli")
def _factory() -> LLMProvider:
    return ClaudeProvider()


class ClaudeProvider(LLMProvider):
    name = "claude_cli"

    def __init__(self):
        self.claude_bin = os.getenv("CLAUDE_BIN") or "claude"

    def generate(self, request: LLMRequest) -> LLMResult:
        """
        Run Claude CLI in stream-json mode and collect assistant text.
        Note: file changes are produced directly by the CLI in cwd; this provider
        does not return a files list.
        """
        messages = "\n".join([m.content for m in request.messages if m.role == "user"])
        cmd = [
            self.claude_bin,
            "-p",
            messages,
            "--output-format",
            "stream-json",
            "--dangerously-skip-permissions",
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=os.getcwd(),
            )
            outputs: List[str] = []
            if proc.stdout:
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("type") == "assistant":
                            for item in data.get("message", {}).get("content", []):
                                if item.get("type") == "text":
                                    outputs.append(item.get("text", ""))
                    except json.JSONDecodeError:
                        outputs.append(line)
            proc.wait(timeout=300)
            return LLMResult(
                text="\n".join(outputs),
                model=None,
                provider=self.name,
            )
        except Exception as e:
            return LLMResult(text=str(e), provider=self.name)
