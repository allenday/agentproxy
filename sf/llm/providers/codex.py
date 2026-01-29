import os
import requests
from typing import List
import json
import shutil
import subprocess

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

    def generate(self, request: LLMRequest) -> LLMResult:
        # Combine system + user messages so Codex CLI sees formatting instructions
        messages = "\n".join([m.content for m in request.messages])
        cmd = [self.codex_bin, "--json", messages]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=os.getcwd(),
            )
            raw_out = proc.stdout or ""
            if proc.returncode != 0:
                return LLMResult(text=proc.stderr or raw_out or "codex cli error", provider=self.name)

            last_text = ""
            for line in raw_out.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "agent_message" and obj.get("text"):
                        last_text = obj["text"]
                    item = obj.get("item", {})
                    if item and item.get("type") == "agent_message" and item.get("text"):
                        last_text = item["text"]
                except Exception:
                    # ignore parse errors; keep raw
                    pass

            return LLMResult(text=last_text or raw_out, provider=self.name)
        except Exception as e:
            return LLMResult(text=str(e), provider=self.name)
