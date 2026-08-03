import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "ros2_core/src/vlm_planner_pkg/src"
sys.path.insert(0, str(SOURCE))

interfaces = types.ModuleType("ai_robot_runtime_interfaces")
messages = types.ModuleType("ai_robot_runtime_interfaces.msg")
messages.CameraFrame = object
interfaces.msg = messages
sys.modules.setdefault("ai_robot_runtime_interfaces", interfaces)
sys.modules.setdefault("ai_robot_runtime_interfaces.msg", messages)

spec = importlib.util.spec_from_file_location(
    "check_llm_proxy", ROOT / "scripts/check_llm_proxy.py"
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CheckLlmProxyTest(unittest.TestCase):
    def test_list_models_strips_both_supported_completion_routes(self) -> None:
        self.assertEqual(
            module.models_endpoint("https://proxy.example/v1/chat/completions"),
            "https://proxy.example/v1/models",
        )
        self.assertEqual(
            module.models_endpoint("https://proxy.example/v1/responses"),
            "https://proxy.example/v1/models",
        )
        self.assertEqual(
            module.models_endpoint("https://proxy.example/v1"),
            "https://proxy.example/v1/models",
        )


if __name__ == "__main__":
    unittest.main()
