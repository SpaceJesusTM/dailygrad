"""Minimal Ollama client: one JSON-returning chat call, and an explicit unload."""

import json
import logging

import requests

from dailygrad.config import OllamaConfig

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5  # seconds
KEEP_ALIVE = "10m"  # keep the model in memory between the requests of one run
UNLOAD_TIMEOUT = (CONNECT_TIMEOUT, 30)


class LLMError(Exception):
    """The model could not be reached, or did not return the JSON object we asked for."""


def chat_json(config: OllamaConfig, system: str, prompt: str, schema: dict) -> dict:
    """Send one system + user message and return the reply, which Ollama constrains to `schema`."""
    body = {
        "model": config.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "format": schema,
        "stream": False,
        "think": config.think,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": config.temperature, "num_ctx": config.context_tokens},
    }
    try:
        response = requests.post(_endpoint(config, "chat"), json=body, timeout=(CONNECT_TIMEOUT, config.timeout_seconds))
    except requests.RequestException as exc:
        raise LLMError(f"cannot reach Ollama at {config.url}: {exc}") from exc
    if response.status_code != 200:
        # Ollama explains itself in the body, e.g. "model ... not found, try pulling it first".
        raise LLMError(f"Ollama returned HTTP {response.status_code}: {response.text[:200]}")

    try:
        reply = json.loads(response.json()["message"]["content"])
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMError(f"Ollama did not return valid JSON: {exc}") from exc
    if not isinstance(reply, dict):
        raise LLMError("Ollama returned JSON that is not an object")
    return reply


def unload(config: OllamaConfig) -> None:
    """Ask Ollama to free the model immediately. Never raises, because it runs in a finally block."""
    try:
        response = requests.post(
            _endpoint(config, "generate"), json={"model": config.model, "keep_alive": 0}, timeout=UNLOAD_TIMEOUT
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        log.warning("could not unload model %s: %s", config.model, exc)


def _endpoint(config: OllamaConfig, name: str) -> str:
    return f"{config.url.rstrip('/')}/api/{name}"
