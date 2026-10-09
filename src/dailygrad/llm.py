"""Minimal Ollama client: one JSON-returning chat call, and an explicit unload.

A request that fails in a way that may pass (a timeout, a dropped connection, HTTP 500, 502,
503 or 504) is tried once more after a short pause. Two limits keep that bounded: a run
makes at most MAX_RETRIES_PER_RUN retries in all, and no request may outlast the run's time
budget, which begin_run starts.
"""

import json
import logging
from dataclasses import dataclass
from time import monotonic, sleep

import requests

from dailygrad.config import OllamaConfig

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5  # seconds
KEEP_ALIVE = "10m"  # keep the model in memory between the requests of one run
UNLOAD_TIMEOUT = (CONNECT_TIMEOUT, 30)

ATTEMPTS = 2  # per request: the first try and one retry
RETRY_PAUSE = 2  # seconds before the retry
MAX_RETRIES_PER_RUN = 3  # across all requests, so a sick server is not asked everything twice
RETRYABLE_STATUS = (500, 502, 503, 504)
MIN_REQUEST_SECONDS = 10  # with less of the budget left than this, a request is not worth starting


class LLMError(Exception):
    """The model could not be reached, or did not return the JSON object we asked for."""


class _Transient(LLMError):
    """A failure that a second attempt may not repeat."""


@dataclass
class _Run:
    deadline: float | None = None  # on the monotonic clock; None means no budget
    retries_left: int = MAX_RETRIES_PER_RUN
    requests: int = 0
    retries: int = 0
    seconds: float = 0.0  # spent waiting for Ollama


_run = _Run()


def begin_run(budget_seconds: float) -> None:
    """Start a run's clock: model requests may use what is left of `budget_seconds` from now."""
    global _run
    _run = _Run(deadline=monotonic() + budget_seconds)


def usage() -> str:
    """One line for the log about the model requests made since begin_run."""
    return f"{_run.requests} model requests, {_run.retries} retried, {_run.seconds:.1f} s waiting for Ollama"


def chat_json(
    config: OllamaConfig, system: str, prompt: str, schema: dict, temperature: float | None = None,
    keep_alive: str | int = KEEP_ALIVE,
) -> dict:  # fmt: skip
    """Send one system + user message and return the reply, which Ollama constrains to `schema`.

    `temperature` overrides the configured temperature for this one request. `keep_alive` is how
    long Ollama keeps the model loaded afterwards: a run keeps it for its other requests and then
    unloads it, while a caller that makes a single request says how long is worth it (0: not at all).
    """
    if temperature is None:
        temperature = config.temperature
    body = {
        "model": config.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "format": schema,
        "stream": False,
        "think": config.think,
        "keep_alive": keep_alive,
        "options": {"temperature": temperature, "num_ctx": config.context_tokens},
    }
    _run.requests += 1
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return _post_chat(config, body)
        except _Transient as exc:
            if attempt == ATTEMPTS or _run.retries_left == 0 or _time_left(after=RETRY_PAUSE) < MIN_REQUEST_SECONDS:
                raise
            _run.retries_left -= 1
            _run.retries += 1
            log.warning("%s; trying once more in %d s", exc, RETRY_PAUSE)
            sleep(RETRY_PAUSE)
    raise AssertionError("unreachable")


def out_of_time() -> bool:
    """True once too little of the run's budget is left for a request to be worth starting."""
    return _time_left() < MIN_REQUEST_SECONDS


def _time_left(after: float = 0) -> float:
    return float("inf") if _run.deadline is None else _run.deadline - monotonic() - after


def _post_chat(config: OllamaConfig, body: dict) -> dict:
    """One attempt. Raises _Transient for a failure worth retrying, LLMError for any other."""
    read_timeout = min(config.timeout_seconds, _time_left())
    if out_of_time():
        raise LLMError("the run's time budget is used up, so the model was not asked")
    started = monotonic()
    try:
        response = requests.post(_endpoint(config, "chat"), json=body, timeout=(CONNECT_TIMEOUT, read_timeout))
    except requests.Timeout as exc:
        raise _Transient(f"Ollama did not answer within {monotonic() - started:.0f} s") from exc
    except requests.RequestException as exc:
        raise _Transient(f"cannot reach Ollama at {config.url}: {exc}") from exc
    finally:
        _run.seconds += monotonic() - started
    if response.status_code != 200:
        # Ollama explains itself in the body, e.g. "model ... not found, try pulling it first".
        kind = _Transient if response.status_code in RETRYABLE_STATUS else LLMError
        raise kind(
            f"Ollama returned HTTP {response.status_code} after {monotonic() - started:.0f} s: {response.text[:200]}"
        )

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
