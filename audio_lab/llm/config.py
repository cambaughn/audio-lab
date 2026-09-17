"""LLM provider configuration — outside source control by design.

~/Library/Application Support/AudioLab/llm.json names the provider, the
model, and WHICH ENVIRONMENT VARIABLE holds the API key:

    {"provider": "anthropic", "model": "claude-opus-5",
     "api_key_env": "ANTHROPIC_API_KEY"}

The key itself lives only in the environment — never in a file this app
reads or writes, never in the repo. A missing or invalid config is a
normal state: the app runs fully on the fake adapter.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from audio_lab.config.settings import APP_DATA_DIR
from audio_lab.llm.adapter import LlmConfigError

LLM_CONFIG_FILENAME = "llm.json"

DEFAULT_MODEL = "claude-opus-5"


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    model: str
    api_key_env: str


def llm_config_path(data_dir: Path | None = None) -> Path:
    return (data_dir or APP_DATA_DIR) / LLM_CONFIG_FILENAME


def load_llm_config(path: Path | None = None) -> LlmConfig:
    """Load and validate llm.json. Raises LlmConfigError on any problem."""
    path = path or llm_config_path()
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise LlmConfigError(
            f"no LLM configuration at {path} — create it to enable the real "
            'adapter, e.g. {"provider": "anthropic", '
            f'"model": "{DEFAULT_MODEL}", "api_key_env": "ANTHROPIC_API_KEY"}}'
        ) from exc
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LlmConfigError(f"unreadable LLM configuration at {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LlmConfigError(f"LLM configuration at {path} is not a JSON object")

    provider = raw.get("provider")
    model = raw.get("model", DEFAULT_MODEL)
    api_key_env = raw.get("api_key_env", "ANTHROPIC_API_KEY")
    if provider != "anthropic":
        raise LlmConfigError(
            f"unsupported provider {provider!r} (only 'anthropic' in v0.1)"
        )
    if not isinstance(model, str) or not model.strip():
        raise LlmConfigError("model must be a non-empty string")
    if not isinstance(api_key_env, str) or not api_key_env.strip():
        raise LlmConfigError("api_key_env must be a non-empty string")
    return LlmConfig(provider=provider, model=model, api_key_env=api_key_env)


def resolve_api_key(llm_config: LlmConfig, environ=None) -> str:
    environ = environ if environ is not None else os.environ
    key = environ.get(llm_config.api_key_env, "").strip()
    if not key:
        raise LlmConfigError(
            f"environment variable {llm_config.api_key_env} is not set — "
            "export the API key there before enabling the real adapter"
        )
    return key
