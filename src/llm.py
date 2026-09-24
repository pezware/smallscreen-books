"""Calls the LLM through the devbox's xAI broker, and nothing else.

There is no API key in this repository or its environment (AGENTS.md, "The
LLM key"). The broker holds it, listens on a unix socket, and replaces the
Authorization header on the way out. So this module speaks plain HTTP to that
socket, with the standard library only, like the rest of the generator.

The broker allows 60 requests a minute. Callers cache their results, so a
rerun sends nothing; this module only has to survive the occasional 429 or
upstream hiccup, and fail loudly when the problem is not transient.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import time

DEFAULT_SOCKET = "/run/xai-broker/xai.sock"

# The mapping of forms to lemmas is a classification task. The reasoning
# models gave the same answers on a probe of 38 hard forms at 23 times the
# latency, so the fast model is the default.
DEFAULT_MODEL = "grok-4.20-0309-non-reasoning"

ATTEMPTS = 5
_RETRYABLE = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


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
    model: str = DEFAULT_MODEL,
    socket_path: str | None = None,
    timeout: float = 300,
    backoff: float = 2.0,
) -> dict:
    """Send one system and one user message; return the answer parsed as JSON.

    Temperature 0 and a JSON response format, because every caller wants a
    structured, repeatable answer. Retries a rate limit or a server error with
    exponential backoff; a client error or an answer that is not JSON fails at
    once, since sending it again would only fail again.
    """
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
    path = socket_path or default_socket_path()

    for attempt in range(1, ATTEMPTS + 1):
        connection = BrokerConnection(path, timeout=timeout)
        try:
            connection.request("POST", "/v1/chat/completions", body, headers)
            response = connection.getresponse()
            status, raw = response.status, response.read()
        finally:
            connection.close()
        if status == 200:
            return _answer(raw)
        if status not in _RETRYABLE or attempt == ATTEMPTS:
            raise LLMError(f"broker answered {status}: {raw[:300]!r}")
        time.sleep(backoff * 2 ** (attempt - 1))
    raise AssertionError("unreachable")


def _answer(raw: bytes) -> dict:
    try:
        content = json.loads(raw)["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise LLMError(f"answer is not JSON: {raw[:300]!r}") from error
