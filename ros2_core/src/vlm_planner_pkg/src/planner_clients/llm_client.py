import base64
import json
import math
import urllib.error
import urllib.request
from typing import Any, Dict

from ai_robot_runtime_interfaces.msg import CameraFrame

from planner_clients.base_client import BasePlannerClient
from planner_clients.schema import PlannerDecision


ALLOWED_ACTIONS = {"move_forward", "turn_left", "turn_right", "stop", "inspect"}
SYSTEM_PROMPT = (
    "Return only JSON with keys action,target,speed,confidence,reason. "
    "Allowed actions: move_forward, turn_left, turn_right, stop, inspect. "
    "Use speed and confidence in [0,1]."
)


class OpenAICompatiblePlannerClient(BasePlannerClient):
    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        timeout_s: float,
        api_style: str = "chat_completions",
        vision_mode: str = "metadata",
        max_image_bytes: int = 1_000_000,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_s = max(float(timeout_s), 0.1)
        self._api_style = api_style.strip().lower()
        if self._api_style not in {"chat_completions", "responses"}:
            raise ValueError("unsupported LLM API style")
        self._vision_mode = vision_mode.strip().lower()
        if self._vision_mode not in {"metadata", "payload_base64"}:
            raise ValueError("unsupported LLM vision mode")
        self._max_image_bytes = max(int(max_image_bytes), 1)
        self._endpoint = self._make_endpoint(self._api_base)

    def plan(self, frame: CameraFrame) -> PlannerDecision:
        payload = self._make_request_payload(frame)

        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "RoboTraceOpt/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self._timeout_s,
            ) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = self._safe_http_error_detail(exc)
            suffix = f" ({detail})" if detail else ""
            raise RuntimeError(
                f"LLM request failed with HTTP status {exc.code}{suffix}"
            ) from exc
        except urllib.error.URLError as exc:
            reason_type = getattr(exc, "reason", exc).__class__.__name__
            raise RuntimeError(f"LLM request failed with network error {reason_type}") from exc

        response_json = json.loads(response_body)
        if self._api_style == "responses":
            content = self._extract_responses_content(response_json)
        else:
            content = self._extract_chat_content(response_json)
        decision_json = json.loads(self._strip_json_block(content))
        return self._decision_from_json(decision_json)

    def _make_request_payload(self, frame: CameraFrame) -> Dict[str, Any]:
        if self._api_style == "responses":
            return {
                "model": self._model,
                "instructions": SYSTEM_PROMPT,
                "input": self._make_responses_user_content(frame),
                "max_output_tokens": 300,
            }
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self._make_user_content(frame)},
            ],
            "temperature": 0.0,
            "max_tokens": 160,
        }

    def _safe_http_error_detail(self, error: urllib.error.HTTPError) -> str:
        try:
            payload = json.loads(error.read(4096).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return ""
        detail = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(detail, dict):
            return ""
        fields = []
        for name in ("type", "code", "message"):
            value = detail.get(name)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                sanitized = str(value).replace(self._api_key, "[REDACTED]")
                sanitized = " ".join(sanitized.split())[:160]
                if sanitized:
                    fields.append(f"{name}={sanitized}")
        return ", ".join(fields)

    def _make_endpoint(self, api_base: str) -> str:
        route = "responses" if self._api_style == "responses" else "chat/completions"
        if api_base.endswith(f"/{route}"):
            return api_base
        return f"{api_base}/{route}"

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

    def _make_user_content(self, frame: CameraFrame) -> Any:
        prompt = self._make_prompt(frame)
        if self._vision_mode == "metadata":
            return prompt

        payload = bytes(frame.payload)
        if not payload:
            raise ValueError("LLM vision payload is empty")
        if len(payload) > self._max_image_bytes:
            raise ValueError("LLM vision payload exceeds configured limit")
        mime_type = self._image_mime_type(str(frame.encoding))
        encoded = base64.b64encode(payload).decode("ascii")
        return [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
            },
        ]

    def _make_responses_user_content(self, frame: CameraFrame) -> Any:
        prompt = self._make_prompt(frame)
        if self._vision_mode == "metadata":
            return prompt

        payload = bytes(frame.payload)
        if not payload:
            raise ValueError("LLM vision payload is empty")
        if len(payload) > self._max_image_bytes:
            raise ValueError("LLM vision payload exceeds configured limit")
        mime_type = self._image_mime_type(str(frame.encoding))
        encoded = base64.b64encode(payload).decode("ascii")
        return [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_url": f"data:{mime_type};base64,{encoded}",
                    },
                ],
            }
        ]

    @staticmethod
    def _image_mime_type(encoding: str) -> str:
        normalized = encoding.strip().lower()
        mime_types = {
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
        }
        if normalized not in mime_types:
            raise ValueError("LLM vision payload has unsupported image encoding")
        return mime_types[normalized]

    @staticmethod
    def _extract_chat_content(response_json: Dict[str, Any]) -> str:
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
    def _extract_responses_content(response_json: Dict[str, Any]) -> str:
        output_text = response_json.get("output_text")
        if isinstance(output_text, str) and output_text:
            return output_text

        output = response_json.get("output")
        if not isinstance(output, list):
            raise ValueError("LLM response missing output")
        parts = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") in {"output_text", "text"}
                    and isinstance(part.get("text"), str)
                ):
                    parts.append(part["text"])
        if parts:
            return "".join(parts)
        raise ValueError("LLM response missing output text")

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
            speed=_finite_bounded_float(raw.get("speed", 0.0), "speed", 0.0, 1.0),
            confidence=_finite_bounded_float(
                raw.get("confidence", 0.0), "confidence", 0.0, 1.0
            ),
            reason=reason,
        )


def _finite_bounded_float(value: Any, field: str, lower: float, upper: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"LLM {field} must be a JSON number")

    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError(f"LLM {field} must be finite")
    if numeric_value < lower or numeric_value > upper:
        raise ValueError(f"LLM {field} must be in [{lower}, {upper}]")
    return numeric_value
