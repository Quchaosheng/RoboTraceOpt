import sys
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


SOURCE = Path(__file__).resolve().parents[2] / "ros2_core/src/vlm_planner_pkg/src"
sys.path.insert(0, str(SOURCE))

interfaces = types.ModuleType("ai_robot_runtime_interfaces")
messages = types.ModuleType("ai_robot_runtime_interfaces.msg")
messages.CameraFrame = object
interfaces.msg = messages
sys.modules.setdefault("ai_robot_runtime_interfaces", interfaces)
sys.modules.setdefault("ai_robot_runtime_interfaces.msg", messages)

from planner_clients.llm_client import OpenAICompatiblePlannerClient  # noqa: E402


class Frame:
    image_path = "frame.jpg"
    frame_id = 7
    width = 2
    height = 1

    def __init__(self, encoding="jpeg", payload=b"\xff\xd8"):
        self.encoding = encoding
        self.payload = payload


class OpenAICompatiblePlannerClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.requests = []

        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers["Content-Length"])
                requests.append(
                    {
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "accept": self.headers.get("Accept"),
                        "user_agent": self.headers.get("User-Agent"),
                        "body": self.rfile.read(length).decode("utf-8"),
                    }
                )
                if self.path.startswith("/reject/"):
                    body = (
                        b'{"error":{"type":"auth","code":"denied",'
                        b'"message":"bad proxy-secret"}}'
                    )
                    self.send_response(401)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                decision = (
                    '{"action":"turn_left","target":"door",'
                    '"speed":0.3,"confidence":0.8,"reason":"clear route"}'
                )
                if self.path.endswith("/responses"):
                    response = {
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": decision}],
                            }
                        ],
                    }
                else:
                    response = {"choices": [{"message": {"content": decision}}]}
                encoded = __import__("json").dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, _format, *_args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def test_uses_openai_compatible_endpoint_and_response_contract(self) -> None:
        client = OpenAICompatiblePlannerClient(
            f"http://127.0.0.1:{self.server.server_port}/v1",
            "proxy-secret",
            "planner-model",
            1.0,
        )

        decision = client.plan(Frame())

        self.assertEqual(decision.action, "turn_left")
        self.assertEqual(decision.target, "door")
        self.assertEqual(self.requests[0]["path"], "/v1/chat/completions")
        self.assertEqual(self.requests[0]["authorization"], "Bearer proxy-secret")
        self.assertEqual(self.requests[0]["accept"], "application/json")
        self.assertEqual(self.requests[0]["user_agent"], "RoboTraceOpt/1.0")
        request = __import__("json").loads(self.requests[0]["body"])
        self.assertEqual(request["model"], "planner-model")
        self.assertEqual(request["temperature"], 0.0)

    def test_uses_responses_endpoint_and_response_contract(self) -> None:
        client = OpenAICompatiblePlannerClient(
            f"http://127.0.0.1:{self.server.server_port}/v1",
            "proxy-secret",
            "planner-model",
            1.0,
            api_style="responses",
        )

        decision = client.plan(Frame())

        self.assertEqual(decision.action, "turn_left")
        self.assertEqual(self.requests[0]["path"], "/v1/responses")
        request = __import__("json").loads(self.requests[0]["body"])
        self.assertEqual(request["model"], "planner-model")
        self.assertIn("Return only JSON", request["instructions"])
        self.assertIn("CameraFrame", request["input"])
        self.assertNotIn("temperature", request)

    def test_http_failure_reports_only_status_code(self) -> None:
        client = OpenAICompatiblePlannerClient(
            f"http://127.0.0.1:{self.server.server_port}/reject",
            "proxy-secret",
            "planner-model",
            1.0,
        )

        with self.assertRaisesRegex(RuntimeError, "HTTP status 401") as raised:
            client.plan(Frame())

        self.assertNotIn("proxy-secret", str(raised.exception))
        self.assertIn("type=auth", str(raised.exception))
        self.assertIn("code=denied", str(raised.exception))
        self.assertIn("message=bad [REDACTED]", str(raised.exception))

    def test_metadata_mode_does_not_embed_image_bytes(self) -> None:
        client = OpenAICompatiblePlannerClient(
            "http://example.test/v1", "key", "model", 1.0
        )

        content = client._make_user_content(Frame(payload=b"private-bytes"))

        self.assertIsInstance(content, str)
        self.assertIn("frame.jpg", content)
        self.assertNotIn("private-bytes", content)

    def test_payload_mode_creates_bounded_data_url(self) -> None:
        client = OpenAICompatiblePlannerClient(
            "http://example.test/v1",
            "key",
            "model",
            1.0,
            vision_mode="payload_base64",
            max_image_bytes=8,
        )

        content = client._make_user_content(Frame())

        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_payload_mode_rejects_unsupported_or_oversized_frames(self) -> None:
        client = OpenAICompatiblePlannerClient(
            "http://example.test/v1",
            "key",
            "model",
            1.0,
            vision_mode="payload_base64",
            max_image_bytes=2,
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            client._make_user_content(Frame(encoding="mock"))
        with self.assertRaisesRegex(ValueError, "exceeds"):
            client._make_user_content(Frame(payload=b"123"))


if __name__ == "__main__":
    unittest.main()
