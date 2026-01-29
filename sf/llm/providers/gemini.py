import os
import json
from ..base import LLMProvider, register_provider
from ..types import LLMRequest, LLMResult, LLMToolCall
from ...gemini_client import GeminiClient


@register_provider("gemini_api")
def _factory() -> LLMProvider:
    return GeminiAPIProvider()


class GeminiAPIProvider(LLMProvider):
    name = "gemini_api"

    def __init__(self):
        self.stub = os.getenv("SF_LLM_STUB", "0") == "1"
        try:
            self.client = GeminiClient()
        except Exception:
            self.client = None
        if not self.client and not self.stub:
            raise ValueError("GEMINI_API_KEY not set")

    def generate(self, request: LLMRequest) -> LLMResult:
        if self.stub or not self.client:
            return LLMResult(text=json.dumps({"files": []}), provider=self.name)
        user_content = "\n".join([m.content for m in request.messages if m.role == "user"])
        system = "\n".join([m.content for m in request.messages if m.role == "system"])
        text = self.client.call(system_prompt=system, user_prompt=user_content)
        return LLMResult(text=text, provider=self.name, model="gemini")
