"""Provider-independent contracts and agents, exposed through lazy imports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ChatMessage": (".base", "ChatMessage"),
    "CopywriterAgent": (".agents", "CopywriterAgent"),
    "ContentRequest": (".models", "ContentRequest"),
    "ContentSource": (".models", "ContentSource"),
    "ContentTask": (".models", "ContentTask"),
    "CriticAgent": (".agents", "CriticAgent"),
    "CriticResult": (".models", "CriticResult"),
    "DEFAULT_ROUTES": (".config", "DEFAULT_ROUTES"),
    "Decision": (".models", "Decision"),
    "DraftPost": (".models", "DraftPost"),
    "GenerationMetadata": (".models", "GenerationMetadata"),
    "ModelRoute": (".config", "ModelRoute"),
    "PolicyContext": (".models", "PolicyContext"),
    "ProviderResponse": (".base", "ProviderResponse"),
    "ResearchAgent": (".agents", "ResearchAgent"),
    "ResearchBrief": (".models", "ResearchBrief"),
    "RewriteAgent": (".agents", "RewriteAgent"),
    "Role": (".config", "Role"),
    "StructuredProvider": (".base", "StructuredProvider"),
    "TokenUsage": (".models", "TokenUsage"),
    "run_research_copywriter": (".agents", "run_research_copywriter"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
