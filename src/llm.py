"""The one way the generator calls an LLM, whichever provider answers.

Three providers, chosen by `SMALLSCREEN_LLM` or a caller's `provider`:

    xai        the devbox's xAI broker, the default. There is no xAI key in
               this repository or its environment (AGENTS.md, "The LLM key").
               The broker holds it, listens on a unix socket, and replaces the
               Authorization header on the way out.
    anthropic  Anthropic's Messages API, with the key read from
               ANTHROPIC_API_KEY. The key lives in the caller's environment
               only, never in the repository or a .env file.
    agent      no network at all. Each request is written to a directory and
               its answer read back from a file, so a coding agent such as
               Claude Code, or a person, can be the model. A missing answer
               raises `PendingAnswer` after its request is on disk; answer it
               and run the command again.

Every provider speaks the standard library only, like the rest of the
generator. Callers cache their results, so a rerun sends nothing; this module
only has to survive the occasional 429 or upstream hiccup, and fail loudly
when the problem is not transient.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

PROVIDERS = ("xai", "anthropic", "agent")
DEFAULT_PROVIDER = "xai"

DEFAULT_SOCKET = "/run/xai-broker/xai.sock"

# The mapping of forms to lemmas is a classification task. The reasoning
# models gave the same answers on a probe of 38 hard forms at 23 times the
# latency, so the fast model is the default.
DEFAULT_MODEL = "grok-4.20-0309-non-reasoning"

DEFAULT_MODELS = {
    "xai": DEFAULT_MODEL,
    "anthropic": "claude-opus-5",
    # A label for provenance, not a model: whoever answers the files.
    "agent": "agent",
}

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 16000

DEFAULT_EXCHANGE = Path("build/llm-exchange")

ATTEMPTS = 5
_RETRYABLE = {429, 500, 502, 503, 504, 529}


class LLMError(RuntimeError):
    pass


class PendingAnswer(LLMError):
    """The agent provider wrote a request that nobody has answered yet."""

    def __init__(self, request: Path, answer: Path):
        super().__init__(f"no answer yet: write {answer} for {request}")
        self.request = request
        self.answer = answer


def provider_name(provider: str | None = None) -> str:
    """The provider asked for, else SMALLSCREEN_LLM, else xai."""
    name = provider or os.environ.get("SMALLSCREEN_LLM") or DEFAULT_PROVIDER
    if name not in PROVIDERS:
        raise LLMError(f"unknown provider {name!r}; choose one of {PROVIDERS}")
    return name


def default_model(provider: str | None = None) -> str:
    """SMALLSCREEN_LLM_MODEL if set, else the provider's default."""
    return (
        os.environ.get("SMALLSCREEN_LLM_MODEL")
        or DEFAULT_MODELS[provider_name(provider)]
    )


class BrokerConnection(http.client.HTTPConnection):
    """HTTP over the broker's unix socket, as AGENTS.md shows."""

    def __init__(self, path: str, **kwargs):
        super().__init__("xai", **kwargs)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def default_socket_path() -> str:
    """XAI_BROKER_SOCKET if set, so a Mac can use an ssh-forwarded socket."""
    return os.environ.get("XAI_BROKER_SOCKET", DEFAULT_SOCKET)


def chat_json(
    system: str,
    user: str,
    model: str | None = None,
    socket_path: str | None = None,
    timeout: float = 300,
    backoff: float = 2.0,
    provider: str | None = None,
    exchange: Path | None = None,
) -> dict:
    """Send one system and one user message; return the answer parsed as JSON.

    Every caller wants a structured, repeatable answer, so each provider is
    asked for JSON and nothing else. A rate limit or a server error is retried
    with exponential backoff; a client error or an answer that is not JSON
    fails at once, since sending it again would only fail again.
    """
    name = provider_name(provider)
    model = model or default_model(name)
    if name == "agent":
        return _agent(system, user, model, exchange)

    def send() -> tuple[int, bytes]:
        if name == "xai":
            return _xai_send(system, user, model, socket_path, timeout)
        return _anthropic_send(system, user, model, timeout)

    for attempt in range(1, ATTEMPTS + 1):
        status, raw = send()
        if status == 200:
            return _xai_answer(raw) if name == "xai" else _anthropic_answer(raw)
        if status not in _RETRYABLE or attempt == ATTEMPTS:
            raise LLMError(f"{name} answered {status}: {raw[:300]!r}")
        time.sleep(backoff * 2 ** (attempt - 1))
    raise AssertionError("unreachable")


def _xai_send(
    system: str, user: str, model: str, socket_path: str | None, timeout: float
) -> tuple[int, bytes]:
    body = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        # A placeholder: the broker replaces it with the real key.
        "Authorization": "Bearer broker",
        "Content-Type": "application/json",
    }
    connection = BrokerConnection(socket_path or default_socket_path(), timeout=timeout)
    try:
        connection.request("POST", "/v1/chat/completions", body, headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _xai_answer(raw: bytes) -> dict:
    try:
        content = json.loads(raw)["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise LLMError(f"answer is not JSON: {raw[:300]!r}") from error


def _anthropic_send(
    system: str, user: str, model: str, timeout: float
) -> tuple[int, bytes]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("provider anthropic needs ANTHROPIC_API_KEY in the environment")
    # No temperature: current Claude models reject sampling parameters, so
    # repeatability comes from the cache, as it does for every provider.
    body = json.dumps(
        {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        os.environ.get("SMALLSCREEN_ANTHROPIC_URL", ANTHROPIC_URL),
        data=body,
        method="POST",
        headers={
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _anthropic_answer(raw: bytes) -> dict:
    try:
        message = json.loads(raw)
        stop = message["stop_reason"]
        text = "".join(
            block["text"] for block in message["content"] if block["type"] == "text"
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise LLMError(f"answer is not a message: {raw[:300]!r}") from error
    # A refusal or a truncated answer is not retried: the same request would
    # stop the same way.
    if stop != "end_turn":
        raise LLMError(f"answer stopped with {stop!r}: {text[:300]!r}")
    return parse_json_text(text)


_FENCE = re.compile(r"^```(?:json)?\s*\n(.*)\n```\s*$", re.DOTALL)


def parse_json_text(text: str) -> dict:
    """The JSON object in a model's text, allowing one markdown code fence."""
    stripped = text.strip()
    fenced = _FENCE.match(stripped)
    try:
        answer = json.loads(fenced.group(1) if fenced else stripped)
    except json.JSONDecodeError as error:
        raise LLMError(f"answer is not JSON: {text[:300]!r}") from error
    if not isinstance(answer, dict):
        raise LLMError(f"answer is not a JSON object: {text[:300]!r}")
    return answer


def request_key(system: str, user: str, model: str) -> str:
    canonical = json.dumps(
        {"model": model, "system": system, "user": user},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _agent(system: str, user: str, model: str, exchange: Path | None) -> dict:
    """Answer from `answers/<key>.json`, or leave the request for someone to answer.

    The system prompt is written once to `systems/<hash>.txt`, because one
    prompt is shared by many requests and can be long. The request file names
    it, carries the user message, and says where the answer goes.
    """
    root = exchange or Path(
        os.environ.get("SMALLSCREEN_LLM_EXCHANGE", str(DEFAULT_EXCHANGE))
    )
    key = request_key(system, user, model)
    answer = root / "answers" / f"{key}.json"
    if answer.exists():
        return parse_json_text(answer.read_text(encoding="utf-8"))

    digest = hashlib.sha256(system.encode("utf-8")).hexdigest()[:16]
    system_path = root / "systems" / f"{digest}.txt"
    request = root / "requests" / f"{key}.json"
    for directory in (system_path.parent, request.parent, answer.parent):
        directory.mkdir(parents=True, exist_ok=True)
    if not system_path.exists():
        system_path.write_text(system, encoding="utf-8")
    request.write_text(
        json.dumps(
            {
                "model": model,
                "system": str(system_path),
                "user": user,
                "answer": str(answer),
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    raise PendingAnswer(request, answer)
