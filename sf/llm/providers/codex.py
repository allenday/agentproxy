import os
import requests
from typing import List
import json
import shutil
import subprocess
import shlex
from typing import Optional

from ..base import LLMProvider, register_provider
from ..types import LLMRequest, LLMResult, LLMToolCall


@register_provider("codex_api")
def _factory_api() -> LLMProvider:
    return CodexAPIProvider()


@register_provider("codex_cli")
def _factory_cli() -> LLMProvider:
    return CodexCLIProvider()


class CodexAPIProvider(LLMProvider):
    name = "codex_api"

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY") or os.getenv("CODEX_API_KEY")
        self.endpoint = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1/chat/completions")
        self.model = os.getenv("SF_LLM_MODEL", "gpt-4.1-mini")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY (or CODEX_API_KEY) not set")

    def generate(self, request: LLMRequest) -> LLMResult:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": request.model or self.model,
            "messages": [m.model_dump() for m in request.messages],
            "temperature": request.temperature,
        }
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = "auto"
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens

        resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        tool_calls: List[LLMToolCall] = []
        if choice.get("message", {}).get("tool_calls"):
            for tc in choice["message"]["tool_calls"]:
                tool_calls.append(
                    LLMToolCall(
                        id=tc.get("id", ""),
                        name=tc["function"]["name"],
                        arguments=tc["function"].get("arguments", {}) if isinstance(tc["function"].get("arguments"), dict) else {"raw": tc["function"].get("arguments")},
                    )
                )
        usage = data.get("usage", {})
        return LLMResult(
            text=choice["message"].get("content") or "",
            tool_calls=tool_calls,
            model=data.get("model"),
            provider=self.name,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )


class CodexCLIProvider(LLMProvider):
    name = "codex_cli"

    def __init__(self):
        self.codex_bin = shutil.which("codex") or os.getenv("CODEX_BIN", "codex")
        if not shutil.which(self.codex_bin):
            raise ValueError("codex CLI not found on PATH (or set CODEX_BIN)")
        # Optional: run Codex via ssh localhost to leverage user login shell permissions.
        self.use_ssh = os.getenv("SF_CODEX_SSH", "0") == "1"
        self.ssh_host = os.getenv("SF_CODEX_SSH_HOST", "localhost")
        # Default session dir inside sandbox to avoid ~/.codex TCC issues.
        self.session_dir = os.getenv(
            "CODEX_SESSION_DIR",
            os.path.join(os.getcwd(), "sandbox", ".codex", "sessions"),
        )
        # Max wall time; allow override. Default 600s to accommodate longer codegen.
        self.exec_timeout = int(os.getenv("SF_CODEX_TIMEOUT", "600"))
        # Extra CLI flags. Default to a permissive workspace-write sandbox.
        raw_flags = os.getenv("SF_CODEX_FLAGS", "--full-auto --sandbox workspace-write")
        self.extra_flags = shlex.split(raw_flags) if raw_flags else []

    def _build_cmd(self, workdir: str, messages: str) -> List[str]:
        """Build codex exec command; prompt passed as single positional arg."""
        flags = self.extra_flags or []
        if self.use_ssh:
            flag_str = " ".join(shlex.quote(f) for f in flags)
            remote_cmd = (
                f"cd {shlex.quote(workdir)} && "
                f"SF_WORKDIR={shlex.quote(workdir)} "
                f"{shlex.quote(self.codex_bin)} exec --json {flag_str} {shlex.quote(messages)}"
            )
            ssh_base = [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                self.ssh_host,
            ]
            return ssh_base + [remote_cmd]
        return [self.codex_bin, "exec", "--json", *flags, messages]

    def generate(self, request: LLMRequest) -> LLMResult:
        # Combine system + user messages so Codex CLI sees formatting instructions
        messages = "\n".join([m.content for m in request.messages])
        workdir = os.getenv("SF_WORKDIR", os.getcwd())
        cmd = self._build_cmd(workdir, messages)
        stdin_data = None
        env = os.environ.copy()
        if self.session_dir:
            os.makedirs(self.session_dir, exist_ok=True)
            env["CODEX_SESSION_DIR"] = self.session_dir
            # Force Codex to use sandboxed HOME so macOS TCC and ~/.codex perms are avoided.
            sandbox_home = os.path.dirname(os.path.dirname(self.session_dir.rstrip("/")))
            env["HOME"] = sandbox_home
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                stdin=subprocess.PIPE if stdin_data is not None else None,
                cwd=None if self.use_ssh else workdir,
                env=env,
            )
            try:
                raw_out, raw_err = proc.communicate(input=stdin_data, timeout=self.exec_timeout)
                timed_out = False
            except subprocess.TimeoutExpired:
                proc.kill()
                raw_out, raw_err = proc.communicate()
                timed_out = True

            raw_out = raw_out or ""
            payload = {
                "files": [],
                "stdout": raw_out,
                "stderr": raw_err,
                "returncode": proc.returncode,
                "cmd": " ".join(cmd),
                "timeout": timed_out,
            }
            if proc.returncode != 0 or timed_out:
                return LLMResult(text=json.dumps(payload), provider=self.name)

            candidate_json = None
            last_text = ""
            for line in raw_out.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "agent_message" and obj.get("text"):
                        txt = obj["text"]
                        last_text = txt
                        if ("files" in txt) or txt.strip().startswith("{"):
                            try:
                                parsed = json.loads(txt)
                                if isinstance(parsed, dict) and "files" in parsed:
                                    candidate_json = txt
                            except Exception:
                                pass
                    item = obj.get("item", {})
                    if item and item.get("type") == "agent_message" and item.get("text"):
                        txt = item["text"]
                        last_text = txt
                        if ("files" in txt) or txt.strip().startswith("{"):
                            try:
                                parsed = json.loads(txt)
                                if isinstance(parsed, dict) and "files" in parsed:
                                    candidate_json = txt
                            except Exception:
                                pass
                except Exception:
                    # ignore parse errors; keep raw
                    pass

            return LLMResult(text=candidate_json or last_text or json.dumps(payload), provider=self.name)
        except Exception as e:
            return LLMResult(text=str(e), provider=self.name)
