import json
import urllib.error
import urllib.request
from typing import Any, Dict

from ai_robot_runtime_interfaces.msg import CameraFrame

from planner_clients.base_client import BasePlannerClient
from planner_clients.schema import PlannerDecision


ALLOWED_ACTIONS = {"move_forward", "turn_left", "turn_right", "stop", "inspect"}


class OpenAICompatiblePlannerClient(BasePlannerClient):
    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        timeout_s: float,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_s = max(float(timeout_s), 0.1)
        self._endpoint = self._make_endpoint(self._api_base)

    def plan(self, frame: CameraFrame) -> PlannerDecision:
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only JSON with keys action,target,speed,confidence,reason. "
                        "Allowed actions: move_forward, turn_left, turn_right, stop, inspect. "
                        "Use speed and confidence in [0,1]."
                    ),
                },
                {
                    "role": "user",
                    "content": self._make_prompt(frame),
                },
            ],
            "temperature": 0.0,
            "max_tokens": 160,
        }

        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self._timeout_s,
            ) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc.__class__.__name__}") from exc

        content = self._extract_content(json.loads(response_body))
        decision_json = json.loads(self._strip_json_block(content))
        return self._decision_from_json(decision_json)

    @staticmethod
    def _make_endpoint(api_base: str) -> str:
        if api_base.endswith("/chat/completions"):
            return api_base
        return f"{api_base}/chat/completions"

    @staticmethod
    def _make_prompt(frame: CameraFrame) -> str:
        return (
            "CameraFrame: "
            f"image_path={frame.image_path}, "
            f"frame_id={int(frame.frame_id)}, "
            f"encoding={frame.encoding}, "
            f"width={int(frame.width)}, "
            f"height={int(frame.height)}. "
            "Choose one safe robot action."
        )

    @staticmethod
    def _extract_content(response_json: Dict[str, Any]) -> str:
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("LLM response missing choices")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ValueError("LLM response choice must be an object")

        message = first_choice.get("message", {})
        if not isinstance(message, dict):
            raise ValueError("LLM response message must be an object")

        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            if parts:
                return "".join(parts)
        raise ValueError("LLM response missing message content")

    @staticmethod
    def _strip_json_block(content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                return "\n".join(lines[1:-1]).strip()
        return stripped

    @staticmethod
    def _decision_from_json(raw: Dict[str, Any]) -> PlannerDecision:
        if not isinstance(raw, dict):
            raise ValueError("LLM decision must be a JSON object")

        action = str(raw.get("action", "")).strip().lower()
        if action not in ALLOWED_ACTIONS:
            raise ValueError("LLM action is not in the allowed action set")

        target = str(raw.get("target", "")).strip()[:64] or "unknown"
        reason = str(raw.get("reason", "")).strip()[:200] or "llm planner output"

        return PlannerDecision(
            action=action,
            target=target,
            speed=_clamp_float(raw.get("speed", 0.0), 0.0, 1.0),
            confidence=_clamp_float(raw.get("confidence", 0.0), 0.0, 1.0),
            reason=reason,
        )


def _clamp_float(value: Any, lower: float, upper: float) -> float:
    numeric_value = float(value)
    return min(max(numeric_value, lower), upper)
