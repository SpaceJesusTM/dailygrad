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


def test_chat_json_temperature_can_be_overridden_for_one_request(post):
    llm.chat_json(CONFIG, "s", "p", SCHEMA, temperature=0.0)
    llm.chat_json(CONFIG, "s", "p", SCHEMA)

    overridden, default = post.calls
    assert overridden["json"]["options"] == {"temperature": 0.0, "num_ctx": 8192}
    assert default["json"]["options"] == {"temperature": 0.2, "num_ctx": 8192}  # the configured value is untouched


@pytest.mark.parametrize(
    "result, message",
    [
        (requests.ConnectionError("connection refused"), "cannot reach Ollama at http://ollama.test:11434/"),
        (requests.Timeout("read timed out"), "Ollama did not answer within"),
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


# --- retries


class Clock:
    """A fake monotonic clock. A scripted request takes as long as the read timeout it was given if it times out."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def server(monkeypatch):
    """Replace requests.post with a script: each call takes the next result. Time is the fake clock's."""
    clock = Clock()

    def fake_post(url, json=None, timeout=None):
        fake_post.calls.append({"url": url, "timeout": timeout, "at": clock.now})
        result = fake_post.script.pop(0) if fake_post.script else chat_reply('{"answer": "42"}')
        if isinstance(result, requests.Timeout):
            clock.now += timeout[1]  # a read timeout uses up exactly the time it was allowed
        elif isinstance(result, tuple):  # (seconds it takes, response)
            clock.now += result[0]
            result = result[1]
        if isinstance(result, Exception):
            raise result
        return result

    fake_post.calls, fake_post.script, fake_post.clock = [], [], clock
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(llm, "monotonic", clock.monotonic)
    monkeypatch.setattr(llm, "sleep", clock.sleep)
    return fake_post


def ask():
    return llm.chat_json(CONFIG, "s", "p", SCHEMA)


TRANSIENT = [
    FakeResponse(500, text="llama runner process no longer running"),
    FakeResponse(502),
    FakeResponse(503),
    FakeResponse(504),
    requests.Timeout("read timed out"),
    requests.ConnectTimeout("connect timed out"),
    requests.ConnectionError("connection reset by peer"),
]


@pytest.mark.parametrize("failure", TRANSIENT)
def test_a_transient_failure_is_retried_once_and_the_retry_can_succeed(server, failure, caplog):
    server.script = [failure]

    with caplog.at_level(logging.WARNING):
        assert ask() == {"answer": "42"}

    assert len(server.calls) == 2
    assert server.calls[0]["url"] == server.calls[1]["url"]  # the same request again
    assert caplog.text.count("trying once more in 2 s") == 1


def test_http_500_then_success_waits_only_the_short_pause(server):
    server.script = [(1.0, FakeResponse(500, text="boom"))]

    assert ask() == {"answer": "42"}
    assert server.calls[1]["at"] - server.calls[0]["at"] == 1.0 + llm.RETRY_PAUSE


def test_a_timeout_then_success_costs_one_timeout_and_the_pause(server):
    server.script = [requests.Timeout("read timed out")]

    assert ask() == {"answer": "42"}
    assert server.clock.now - 1000.0 == CONFIG.timeout_seconds + llm.RETRY_PAUSE


@pytest.mark.parametrize("failure", TRANSIENT)
def test_a_request_that_keeps_failing_is_tried_exactly_twice(server, failure):
    server.script = [failure] * 10

    with pytest.raises(llm.LLMError):
        ask()

    assert len(server.calls) == llm.ATTEMPTS == 2


@pytest.mark.parametrize(
    "failure",
    [
        FakeResponse(404, text="model 'test-model' not found"),
        FakeResponse(400, text="invalid format"),
        FakeResponse(401),
        chat_reply("not json"),
        chat_reply("[1, 2, 3]"),
        FakeResponse(200, payload={"error": "something"}),
    ],
)
def test_permanent_failures_are_not_retried(server, failure):
    server.script = [failure]

    with pytest.raises(llm.LLMError):
        ask()

    assert len(server.calls) == 1 and server.clock.now == 1000.0  # no second request and no pause


def test_a_successful_request_is_sent_once_with_no_pause(server):
    for _ in range(7):
        assert ask() == {"answer": "42"}

    assert len(server.calls) == 7 and server.clock.now == 1000.0
    assert all(call["timeout"] == (5, 180) for call in server.calls)


def test_a_run_makes_at_most_three_retries_however_many_requests_fail(server):
    llm.begin_run(10_000)
    server.script = [FakeResponse(500)] * 100

    for _ in range(7):  # a whole run: selection, five summaries and the lesson
        with pytest.raises(llm.LLMError):
            ask()

    assert len(server.calls) == 7 + llm.MAX_RETRIES_PER_RUN == 10
    assert llm.usage().startswith("7 model requests, 3 retried")


def test_begin_run_restores_the_retry_allowance(server):
    test_a_run_makes_at_most_three_retries_however_many_requests_fail(server)
    server.calls.clear()
    llm.begin_run(10_000)
    server.script = [FakeResponse(500)]

    assert ask() == {"answer": "42"} and len(server.calls) == 2


def test_no_request_may_outlast_the_run_budget(server):
    llm.begin_run(450)
    server.clock.now += 300  # fetching and earlier requests used 300 s
    server.script = [requests.Timeout("read timed out")] * 5

    with pytest.raises(llm.LLMError, match="did not answer within 150 s"):
        ask()

    assert [call["timeout"] for call in server.calls] == [(5, 150)]  # capped, and nothing left for a retry
    assert server.clock.now == 1000.0 + 450


def test_a_retry_gets_only_the_time_that_is_left(server):
    llm.begin_run(300)
    server.script = [requests.Timeout("read timed out")] * 5

    with pytest.raises(llm.LLMError):
        ask()

    assert [call["timeout"][1] for call in server.calls] == [180, 300 - 180 - llm.RETRY_PAUSE]
    assert server.clock.now == 1000.0 + 300


def test_with_the_budget_used_up_ollama_is_not_asked_at_all(server):
    llm.begin_run(450)
    server.clock.now += 450 - llm.MIN_REQUEST_SECONDS + 1

    with pytest.raises(llm.LLMError, match="time budget is used up"):
        ask()

    assert server.calls == []


def test_a_whole_run_of_timeouts_ends_at_the_budget(server):
    """The worst case: every request hangs. Seven requests could wait 7 x 180 s x 2; the budget stops that."""
    llm.begin_run(450)
    server.script = [requests.Timeout("read timed out")] * 100

    for _ in range(7):
        with pytest.raises(llm.LLMError):
            ask()

    assert server.clock.now - 1000.0 <= 450
    assert len(server.calls) == 3  # 180 s, 180 s, then the 88 s that were left


def test_without_begin_run_there_is_no_budget(server):
    server.clock.now += 10_000_000

    assert ask() == {"answer": "42"} and server.calls[0]["timeout"] == (5, 180)


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
