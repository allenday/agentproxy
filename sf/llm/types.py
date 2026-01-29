from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMToolCall(BaseModel):
    id: str
    type: str = "function"
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class LLMRequest(BaseModel):
    messages: List[LLMMessage]
    tools: Optional[List[Dict[str, Any]]] = None
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    provider: Optional[str] = None


class LLMResult(BaseModel):
    text: str = ""
    tool_calls: List[LLMToolCall] = Field(default_factory=list)
    model: Optional[str] = None
    provider: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
