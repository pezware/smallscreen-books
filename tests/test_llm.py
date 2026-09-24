"""Checks the broker client against a fake broker on a unix socket."""

import http.server
import json
import socketserver
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import llm  # noqa: E402


class FakeBroker(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Answers each POST with the next scripted (status, body) pair."""

    daemon_threads = True

    def __init__(self, path: str, replies: list[tuple[int, dict]]):
        self.replies = list(replies)
        self.requests: list[dict] = []
        super().__init__(path, Handler)


class Handler(http.server.BaseHTTPRequestHandler):
    def address_string(self):
        return "unix"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.server.requests.append(
            {"path": self.path, "body": json.loads(self.rfile.read(length))}
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
            "system", "user", model="m", socket_path=server.server_address, backoff=0
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


if __name__ == "__main__":
    unittest.main()
