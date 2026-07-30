#!/usr/bin/env python3
"""Call the configured OpenAI-compatible planner without exposing secrets."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PLANNER_SOURCE = REPOSITORY_ROOT / "ros2_core" / "src" / "vlm_planner_pkg" / "src"
if str(PLANNER_SOURCE) not in sys.path:
    sys.path.insert(0, str(PLANNER_SOURCE))

from ai_robot_runtime_interfaces.msg import CameraFrame  # noqa: E402
from planner_clients.llm_client import OpenAICompatiblePlannerClient  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument(
        "--api-style",
        choices=("chat_completions", "responses"),
        default="chat_completions",
        help="OpenAI-compatible route to probe",
    )
    return parser.parse_args()


def models_endpoint(api_base: str) -> str:
    base = api_base.rstrip("/")
    for route in ("/chat/completions", "/responses"):
        if base.endswith(route):
            base = base[: -len(route)]
            break
    return f"{base}/models"


def list_models() -> int:
    endpoint = models_endpoint(os.environ["LLM_API_BASE"])
    request = urllib.request.Request(
        endpoint,
        headers={
            "Authorization": f"Bearer {os.environ['LLM_API_KEY']}",
            "Accept": "application/json",
            "User-Agent": "RoboTraceOpt/1.0",
        },
    )
    started_ns = time.monotonic_ns()
    try:
        with urllib.request.urlopen(request, timeout=10.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "http_status": error.code,
                    "duration_ns": time.monotonic_ns() - started_ns,
                }
            )
        )
        return 1
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": error.__class__.__name__,
                    "duration_ns": time.monotonic_ns() - started_ns,
                }
            )
        )
        return 1
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    model_ids = sorted(
        str(row["id"])
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "model_count": len(model_ids),
                "models": model_ids,
                "duration_ns": time.monotonic_ns() - started_ns,
            },
            sort_keys=True,
        )
    )
    return 0


def probe_responses() -> int:
    api_base = os.environ["LLM_API_BASE"].rstrip("/")
    if api_base.endswith("/responses"):
        endpoint = api_base
    else:
        endpoint = f"{api_base}/responses"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(
            {
                "model": os.environ["LLM_MODEL"],
                "input": "Reply with exactly OK.",
                "max_output_tokens": 32,
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['LLM_API_KEY']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "RoboTraceOpt/1.0",
        },
        method="POST",
    )
    started_ns = time.monotonic_ns()
    try:
        with urllib.request.urlopen(request, timeout=90.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        safe_error = {}
        try:
            payload = json.loads(error.read(4096).decode("utf-8"))
            detail = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(detail, dict):
                for name in ("type", "code", "message"):
                    value = detail.get(name)
                    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                        safe_error[name] = (
                            " ".join(str(value).split())
                            .replace(os.environ["LLM_API_KEY"], "[REDACTED]")[:200]
                        )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        print(
            json.dumps(
                {
                    "status": "failed",
                    "http_status": error.code,
                    "error": safe_error,
                    "duration_ns": time.monotonic_ns() - started_ns,
                },
                sort_keys=True,
            )
        )
        return 1
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": error.__class__.__name__,
                    "duration_ns": time.monotonic_ns() - started_ns,
                },
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "status": "passed",
                "http_status": response.status,
                "response_status": payload.get("status") if isinstance(payload, dict) else None,
                "response_model": payload.get("model") if isinstance(payload, dict) else None,
                "has_output": bool(payload.get("output")) if isinstance(payload, dict) else False,
                "duration_ns": time.monotonic_ns() - started_ns,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    args = parse_args()
    required = ("LLM_API_BASE", "LLM_API_KEY", "LLM_MODEL")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print(json.dumps({"status": "blocked", "reason": "missing_environment"}))
        return 2
    if args.list_models:
        return list_models()
    if args.api_style == "responses":
        return probe_responses()

    frame = CameraFrame()
    frame.image_path = "proxy_connectivity_smoke.jpg"
    frame.frame_id = 1
    frame.encoding = "mock"
    frame.width = 640
    frame.height = 480
    started_ns = time.monotonic_ns()
    try:
        decision = OpenAICompatiblePlannerClient(
            api_base=os.environ["LLM_API_BASE"],
            api_key=os.environ["LLM_API_KEY"],
            model=os.environ["LLM_MODEL"],
            timeout_s=float(os.environ.get("LLM_TIMEOUT_S", "10.0")),
            vision_mode="metadata",
        ).plan(frame)
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": error.__class__.__name__,
                    "error_message": str(error),
                    "duration_ns": time.monotonic_ns() - started_ns,
                }
            )
        )
        return 1

    print(
        json.dumps(
            {
                "status": "passed",
                "duration_ns": time.monotonic_ns() - started_ns,
                "decision": {
                    "action": decision.action,
                    "target": decision.target,
                    "speed": decision.speed,
                    "confidence": decision.confidence,
                    "reason": decision.reason,
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
