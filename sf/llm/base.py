import os
from typing import Dict, Callable

from .types import LLMRequest, LLMResult


class LLMProvider:
    name: str = "base"

    def generate(self, request: LLMRequest) -> LLMResult:
        raise NotImplementedError


_registry: Dict[str, Callable[[], LLMProvider]] = {}


def register_provider(name: str):
    def wrapper(factory: Callable[[], LLMProvider]):
        _registry[name] = factory
        return factory
    return wrapper


def get_provider(name: str = None) -> LLMProvider:
    provider_name = name or os.getenv("SF_LLM_PROVIDER", "claude")
    factory = _registry.get(provider_name)
    if not factory:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
    return factory()
