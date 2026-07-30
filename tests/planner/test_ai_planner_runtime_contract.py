import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLANNER = ROOT / "ros2_core/src/vlm_planner_pkg/src/vlm_planner_node.py"
BRINGUP = ROOT / "ros2_core/src/runtime_bringup/launch/ai_runtime.launch.py"


class AiPlannerRuntimeContractTest(unittest.TestCase):
    def test_bringup_exposes_all_llm_parameters_to_the_planner(self) -> None:
        source = BRINGUP.read_text(encoding="utf-8")
        tree = ast.parse(source)
        declared = {
            ast.literal_eval(node.args[0])
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "DeclareLaunchArgument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        }
        expected = {
            "planner_backend",
            "llm_provider",
            "llm_api_base",
            "llm_api_key_env",
            "llm_model",
            "llm_timeout_s",
            "llm_vision_mode",
            "llm_max_image_bytes",
            "fallback_to_mock",
        }
        self.assertTrue(expected <= declared)
        for name in expected:
            self.assertIn(f'"{name}": ParameterValue(', source)

    def test_planner_records_backend_duration_and_failure(self) -> None:
        source = PLANNER.read_text(encoding="utf-8")
        tree = ast.parse(source)
        planner_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "VlmPlannerNode"
        )
        initializer = next(
            node
            for node in planner_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "__init__"
        )
        initialized_attributes = {
            target.attr
            for node in ast.walk(initializer)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        }
        self.assertIn("_llm_vision_mode", initialized_attributes)
        self.assertIn("_llm_max_image_bytes", initialized_attributes)
        self.assertIn('"planner_backend_failure"', source)
        self.assertIn("planning_finished_ns - planning_started_ns", source)
        self.assertIn("event.duration_ns = max(int(duration_ns), 0)", source)


if __name__ == "__main__":
    unittest.main()
