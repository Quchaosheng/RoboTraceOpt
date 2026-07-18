import unittest

try:
    from ai_robot_runtime_interfaces.msg import CameraFrame
except ModuleNotFoundError:
    CameraFrame = None  # type: ignore[assignment]


@unittest.skipIf(CameraFrame is None, "ROS 2 interface package is not sourced")
class MockPlannerTest(unittest.TestCase):
    def test_returns_a_structured_decision(self) -> None:
        from planner_clients.mock_client import MockPlannerClient

        assert CameraFrame is not None
        decision = MockPlannerClient(delay_ms=0).plan(CameraFrame())

        self.assertEqual(decision.action, "move_forward")
        self.assertEqual(decision.target, "front")
        self.assertEqual(decision.speed, 0.2)
        self.assertEqual(decision.confidence, 0.9)
