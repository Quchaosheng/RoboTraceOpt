import unittest
from pathlib import Path


class CanBridgeTimerLifecycleTest(unittest.TestCase):
    def test_mock_ack_timers_cancel_after_first_fire_and_stop_at_shutdown(self) -> None:
        source = (
            Path(__file__).resolve().parents[2]
            / "ros2_core"
            / "src"
            / "can_bridge_pkg"
            / "src"
            / "can_bridge_node.cpp"
        ).read_text(encoding="utf-8")

        mock_ack = source.split("void CanBridgeNode::schedule_mock_ack", 1)[1].split(
            "void CanBridgeNode::schedule_ack_timeout", 1
        )[0]
        timeout = source.split("void CanBridgeNode::schedule_ack_timeout", 1)[1].split(
            "bool CanBridgeNode::mock_ack_will_arrive", 1
        )[0]
        for timer_body in (mock_ack, timeout):
            self.assertIn("!rclcpp::ok() || shutting_down_.load()", timer_body)
            self.assertIn("timer->cancel()", timer_body)
            self.assertIn("catch (const rclcpp::exceptions::RCLError & error)", timer_body)
            self.assertIn("throw;", timer_body)


if __name__ == "__main__":
    unittest.main()
