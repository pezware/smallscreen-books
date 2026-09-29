"""Checks each provider: xAI against a fake broker on a unix socket, Anthropic
against a fake server on localhost, and the agent against files on disk."""

import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import llm  # noqa: E402


class FakeBroker(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Answers each POST with the next scripted (status, body) pair."""

    daemon_threads = True

    def __init__(self, path: str, replies: list[tuple[int, dict]]):
        self.replies = list(replies)
        self.requests: list[dict] = []
        super().__init__(path, Handler)


class FakeAnthropic(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """The same scripted replies, over TCP on localhost."""

    daemon_threads = True

    def __init__(self, replies: list[tuple[int, dict]]):
        self.replies = list(replies)
        self.requests: list[dict] = []
        super().__init__(("127.0.0.1", 0), Handler)


class Handler(http.server.BaseHTTPRequestHandler):
    def address_string(self):
        return "unix"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.server.requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers),
                "body": json.loads(self.rfile.read(length)),
            }
        )
        status, body = self.server.replies.pop(0)
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def completion(content: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


class ChatJson(unittest.TestCase):
    def serve(self, *replies: tuple[int, dict]) -> FakeBroker:
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        server = FakeBroker(str(Path(tmp) / "xai.sock"), list(replies))
        threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def call(self, server: FakeBroker) -> dict:
        return llm.chat_json(
            "system",
            "user",
            model="m",
            socket_path=server.server_address,
            backoff=0,
            provider="xai",
        )

    def test_returns_the_parsed_json_answer(self):
        server = self.serve((200, completion({"ok": 1})))
        self.assertEqual(self.call(server), {"ok": 1})

    def test_posts_to_the_chat_completions_path(self):
        server = self.serve((200, completion({})))
        self.call(server)
        self.assertEqual(server.requests[0]["path"], "/v1/chat/completions")

    def test_asks_for_a_json_object_at_temperature_zero(self):
        server = self.serve((200, completion({})))
        self.call(server)
        body = server.requests[0]["body"]
        self.assertEqual(
            (body["temperature"], body["response_format"]),
            (0, {"type": "json_object"}),
        )

    def test_retries_after_a_rate_limit(self):
        server = self.serve((429, {"error": "slow down"}), (200, completion({"ok": 1})))
        self.assertEqual(self.call(server), {"ok": 1})

    def test_a_client_error_fails_at_once_with_the_status(self):
        server = self.serve((400, {"error": "bad"}), (200, completion({})))
        with self.assertRaisesRegex(llm.LLMError, "400"):
            self.call(server)

    def test_gives_up_after_the_retry_budget(self):
        server = self.serve(*[(503, {})] * llm.ATTEMPTS)
        with self.assertRaisesRegex(llm.LLMError, "503"):
            self.call(server)

    def test_an_answer_that_is_not_json_fails_loudly(self):
        reply = {"choices": [{"message": {"content": "not json"}}]}
        server = self.serve((200, reply))
        with self.assertRaisesRegex(llm.LLMError, "not JSON"):
            self.call(server)


def message(text: str, stop: str = "end_turn") -> dict:
    return {
        "role": "assistant",
        "stop_reason": stop,
        "content": [
            {"type": "thinking", "thinking": ""},
            {"type": "text", "text": text},
        ],
    }


class Anthropic(unittest.TestCase):
    def serve(self, *replies: tuple[int, dict]) -> FakeAnthropic:
        server = FakeAnthropic(list(replies))
        threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        host, port = server.server_address
        env = {
            "ANTHROPIC_API_KEY": "test-key",
            "SMALLSCREEN_ANTHROPIC_URL": f"http://{host}:{port}/v1/messages",
            "NO_PROXY": "*",
            "no_proxy": "*",
        }
        self.enterContext(mock.patch.dict(os.environ, env))
        return server

    def call(self) -> dict:
        return llm.chat_json("system", "user", provider="anthropic", backoff=0)

    def test_returns_the_json_in_the_text_block(self):
        self.serve((200, message('{"ok": 1}')))
        self.assertEqual(self.call(), {"ok": 1})

    def test_accepts_a_json_code_fence(self):
        self.serve((200, message('```json\n{"ok": 1}\n```')))
        self.assertEqual(self.call(), {"ok": 1})

    def test_sends_the_key_the_version_and_the_default_model(self):
        server = self.serve((200, message("{}")))
        self.call()
        request = server.requests[0]
        headers = {k.lower(): v for k, v in request["headers"].items()}
        self.assertEqual(request["path"], "/v1/messages")
        self.assertEqual(headers["x-api-key"], "test-key")
        self.assertEqual(headers["anthropic-version"], llm.ANTHROPIC_VERSION)
        self.assertEqual(request["body"]["model"], llm.DEFAULT_MODELS["anthropic"])
        self.assertEqual(request["body"]["system"], "system")

    def test_retries_when_overloaded(self):
        self.serve((529, {"error": "overloaded"}), (200, message('{"ok": 1}')))
        self.assertEqual(self.call(), {"ok": 1})

    def test_a_client_error_fails_at_once_with_the_status(self):
        self.serve((400, {"error": "bad"}), (200, message("{}")))
        with self.assertRaisesRegex(llm.LLMError, "400"):
            self.call()

    def test_a_refusal_fails_loudly(self):
        self.serve((200, message("", stop="refusal")))
        with self.assertRaisesRegex(llm.LLMError, "refusal"):
            self.call()

    def test_a_truncated_answer_fails_loudly(self):
        self.serve((200, message('{"ok"', stop="max_tokens")))
        with self.assertRaisesRegex(llm.LLMError, "max_tokens"):
            self.call()

    def test_no_key_fails_before_any_request(self):
        server = self.serve((200, message("{}")))
        with (
            mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}),
            self.assertRaisesRegex(llm.LLMError, "ANTHROPIC_API_KEY"),
        ):
            self.call()
        self.assertEqual(server.requests, [])


class Agent(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def call(self, user: str = "user") -> dict:
        return llm.chat_json(
            "system", user, model="m", provider="agent", exchange=self.root
        )

    def test_an_unanswered_request_is_written_and_raises(self):
        with self.assertRaises(llm.PendingAnswer) as caught:
            self.call()
        request = json.loads(caught.exception.request.read_text(encoding="utf-8"))
        self.assertEqual(request["user"], "user")
        self.assertEqual(Path(request["system"]).read_text(encoding="utf-8"), "system")
        self.assertEqual(request["answer"], str(caught.exception.answer))

    def test_the_answer_file_is_the_reply(self):
        with self.assertRaises(llm.PendingAnswer) as caught:
            self.call()
        caught.exception.answer.write_text('{"ok": 1}', encoding="utf-8")
        self.assertEqual(self.call(), {"ok": 1})

    def test_a_different_message_is_a_different_request(self):
        with self.assertRaises(llm.PendingAnswer) as first:
            self.call("one")
        with self.assertRaises(llm.PendingAnswer) as second:
            self.call("two")
        self.assertNotEqual(first.exception.answer, second.exception.answer)

    def test_an_answer_that_is_not_json_fails_loudly(self):
        with self.assertRaises(llm.PendingAnswer) as caught:
            self.call()
        caught.exception.answer.write_text("not json", encoding="utf-8")
        with self.assertRaisesRegex(llm.LLMError, "not JSON"):
            self.call()


class ProviderChoice(unittest.TestCase):
    def test_xai_is_the_default(self):
        with mock.patch.dict(os.environ, {"SMALLSCREEN_LLM": ""}):
            self.assertEqual(llm.provider_name(), "xai")
            self.assertEqual(llm.default_model(), llm.DEFAULT_MODEL)

    def test_the_environment_chooses_the_provider(self):
        with mock.patch.dict(os.environ, {"SMALLSCREEN_LLM": "anthropic"}):
            self.assertEqual(llm.provider_name(), "anthropic")
            self.assertEqual(llm.provider_name("agent"), "agent")

    def test_the_environment_can_override_the_model(self):
        env = {"SMALLSCREEN_LLM": "anthropic", "SMALLSCREEN_LLM_MODEL": "other"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(llm.default_model(), "other")

    def test_an_unknown_provider_is_refused(self):
        with self.assertRaisesRegex(llm.LLMError, "unknown provider"):
            llm.provider_name("openai")


if __name__ == "__main__":
    unittest.main()
