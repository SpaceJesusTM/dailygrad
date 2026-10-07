"""The Ollama client, with requests.post faked."""

import json
import logging

import pytest
import requests

from dailygrad import llm
from dailygrad.config import OllamaConfig

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
CONFIG = OllamaConfig(url="http://ollama.test:11434/", model="test-model")


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self.payload = payload
        self.text = text

    def json(self):
        if self.payload is None:
            raise ValueError("no JSON")
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def chat_reply(content):
    return FakeResponse(payload={"message": {"role": "assistant", "content": content}, "done": True})


@pytest.fixture
def post(monkeypatch):
    """Replace requests.post. Set post.result to a response or an exception; calls are recorded."""

    def fake_post(url, json=None, timeout=None):
        fake_post.calls.append({"url": url, "json": json, "timeout": timeout})
        if isinstance(fake_post.result, Exception):
            raise fake_post.result
        return fake_post.result

    fake_post.calls = []
    fake_post.result = chat_reply('{"answer": "42"}')
    monkeypatch.setattr(requests, "post", fake_post)
    return fake_post


def test_chat_json_sends_a_schema_constrained_request(post):
    assert llm.chat_json(CONFIG, "You are terse.", "What is 6 x 7?", SCHEMA) == {"answer": "42"}

    (call,) = post.calls
    assert call["url"] == "http://ollama.test:11434/api/chat"
    assert call["timeout"] == (5, 180)
    assert call["json"] == {
        "model": "test-model",
        "messages": [
            {"role": "system", "content": "You are terse."},
            {"role": "user", "content": "What is 6 x 7?"},
        ],
        "format": SCHEMA,
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }


def test_chat_json_uses_the_configured_model_settings(post):
    config = OllamaConfig(model="other:7b", context_tokens=4096, temperature=0.0, think=True, timeout_seconds=600)

    llm.chat_json(config, "s", "p", SCHEMA)

    (call,) = post.calls
    assert call["url"] == "http://localhost:11434/api/chat"
    assert call["timeout"] == (5, 600)
    assert call["json"]["model"] == "other:7b"
    assert call["json"]["think"] is True
    assert call["json"]["options"] == {"temperature": 0.0, "num_ctx": 4096}


@pytest.mark.parametrize(
    "result, message",
    [
        (requests.ConnectionError("connection refused"), "cannot reach Ollama at http://ollama.test:11434/"),
        (requests.Timeout("read timed out"), "cannot reach Ollama"),
        (FakeResponse(404, text='{"error":"model \'test-model\' not found"}'), "HTTP 404.*not found"),
        (FakeResponse(200, payload=None), "did not return valid JSON"),
        (FakeResponse(200, payload={"error": "something"}), "did not return valid JSON"),
        (chat_reply("Sure! Here is the answer: 42"), "did not return valid JSON"),
        (chat_reply('{"answer": "cut off'), "did not return valid JSON"),
        (chat_reply("[1, 2, 3]"), "not an object"),
    ],
)
def test_chat_json_failures_raise_llm_error(post, result, message):
    post.result = result

    with pytest.raises(llm.LLMError, match=message):
        llm.chat_json(CONFIG, "s", "p", SCHEMA)


def test_unload_sets_keep_alive_to_zero(post):
    post.result = FakeResponse(payload={"done": True, "done_reason": "unload"})

    llm.unload(CONFIG)

    (call,) = post.calls
    assert call["url"] == "http://ollama.test:11434/api/generate"
    assert call["json"] == {"model": "test-model", "keep_alive": 0}
    assert json.dumps(call["json"])  # a plain JSON body


@pytest.mark.parametrize("result", [requests.ConnectionError("connection refused"), FakeResponse(500)])
def test_unload_never_raises(post, result, caplog):
    post.result = result

    with caplog.at_level(logging.WARNING):
        llm.unload(CONFIG)

    assert "could not unload model test-model" in caplog.text
