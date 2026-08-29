from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path

from config.settings import OLLAMA_MODEL, PLANNER_MODEL, ROUTER_MODEL
from app.llm.base import LLMProvider


@dataclass
class ModelConfig:
    provider: str
    model: str


_MODEL_CONFIGS: dict[str, ModelConfig] = {
    "router": ModelConfig(
        provider=os.environ.get("JARVIS_ROUTER_PROVIDER", "ollama"),
        model=os.environ.get("JARVIS_ROUTER_MODEL", ROUTER_MODEL),
    ),
    "planner": ModelConfig(
        provider=os.environ.get("JARVIS_PLANNER_PROVIDER", "ollama"),
        model=os.environ.get("JARVIS_PLANNER_MODEL", PLANNER_MODEL),
    ),
    "worker": ModelConfig(
        provider=os.environ.get("JARVIS_WORKER_PROVIDER", "ollama"),
        model=os.environ.get("JARVIS_WORKER_MODEL", OLLAMA_MODEL),
    ),
    "default": ModelConfig(
        provider=os.environ.get("JARVIS_DEFAULT_PROVIDER", "ollama"),
        model=os.environ.get("JARVIS_DEFAULT_MODEL", OLLAMA_MODEL),
    ),
}

CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "llm_config.json"


def _load_persisted_configs() -> None:
    if not CONFIG_FILE.exists():
        return
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for role in ("default", "router", "planner", "worker"):
        value = data.get(role)
        if isinstance(value, dict) and isinstance(value.get("provider"), str) and isinstance(value.get("model"), str):
            if value["provider"].strip() and value["model"].strip():
                _MODEL_CONFIGS[role] = ModelConfig(
                    provider=value["provider"].strip().lower(),
                    model=value["model"].strip(),
                )


def _persist_configs() -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = CONFIG_FILE.with_suffix(".tmp")
    temporary_file.write_text(
        json.dumps({role: vars(config) for role, config in _MODEL_CONFIGS.items()}, indent=2),
        encoding="utf-8",
    )
    temporary_file.replace(CONFIG_FILE)


_load_persisted_configs()


def get_model_config(role: str) -> ModelConfig:
    """Return a copy so callers cannot mutate the shared configuration accidentally."""
    config = _MODEL_CONFIGS.get(role, _MODEL_CONFIGS["default"])
    return ModelConfig(provider=config.provider, model=config.model)


def set_model_config(role: str, *, provider: str, model: str) -> ModelConfig:
    """Update and persist a role configuration for subsequent requests."""
    if role not in ("default", "router", "planner", "worker"):
        raise ValueError(f"Unknown role '{role}'")
    if provider.strip().lower() not in ("ollama", "gemini", "anthropic", "openai"):
        raise ValueError("Unsupported provider. Choose ollama, gemini, anthropic, or openai.")
    if not provider.strip():
        raise ValueError("provider must not be empty")
    if not model.strip():
        raise ValueError("model must not be empty")
    _MODEL_CONFIGS[role] = ModelConfig(provider=provider.strip().lower(), model=model.strip())
    _persist_configs()
    return get_model_config(role)


def get_provider(name: str) -> LLMProvider:
    """
    Create the configured provider implementation without exposing provider-specific
    SDKs to the agents.

    Supported providers: ollama (default), gemini, anthropic, openai.
    Paid providers are strictly opt-in — Ollama remains the safe default.
    DO NOT add automatic fallback chains to paid providers here.
    """
    provider_name = name.strip().lower()

    if provider_name == "ollama":
        from app.llm.ollama import OllamaProvider
        return OllamaProvider()

    if provider_name == "gemini":
        from app.llm.gemini import GeminiProvider
        return GeminiProvider()

    if provider_name in ("anthropic", "claude"):
        from app.llm.anthropic import AnthropicProvider
        return AnthropicProvider()

    if provider_name in ("openai", "gpt"):
        from app.llm.openai import OpenAIProvider
        return OpenAIProvider()

    raise ValueError(
        f"Unsupported LLM provider: '{name}'. "
        f"Supported providers: ollama, gemini, anthropic, openai."
    )
