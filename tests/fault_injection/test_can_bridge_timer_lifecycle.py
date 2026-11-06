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
            "void CanBridgeNode::on_ack_timeout", 1
        )[0]
        for timer_body in (mock_ack, timeout):
            self.assertIn("!rclcpp::ok() || shutting_down_.load()", timer_body)
            self.assertIn("timer->cancel()", timer_body)
            self.assertIn(
                "catch (const rclcpp::exceptions::RCLError & error)", timer_body
            )
            self.assertIn("throw;", timer_body)

    def test_ack_receiver_is_opened_before_the_frame_is_sent(self) -> None:
        source = (
            Path(__file__).resolve().parents[2]
            / "ros2_core"
            / "src"
            / "can_bridge_pkg"
            / "src"
            / "can_bridge_node.cpp"
        ).read_text(encoding="utf-8")

        send_attempt = source.split("void CanBridgeNode::send_attempt", 1)[1].split(
            "void CanBridgeNode::publish_probe_completion", 1
        )[0]

        self.assertLess(
            send_attempt.index("open_socketcan_ack_socket"),
            send_attempt.index("send_frame(frame"),
        )
        self.assertIn("start_ack_wait(command, frame, retry_count, ack_socket_fd)", send_attempt)

    def test_finished_ack_threads_and_cancelled_timers_are_reclaimed(self) -> None:
        root = Path(__file__).resolve().parents[2] / "ros2_core" / "src"
        source = (
            root / "can_bridge_pkg" / "src" / "can_bridge_node.cpp"
        ).read_text(encoding="utf-8")
        header = (
            root / "can_bridge_pkg" / "include" / "can_bridge_pkg" / "can_bridge_node.hpp"
        ).read_text(encoding="utf-8")

        self.assertIn("ack_threads_.spawn(", source)
        self.assertIn("ack_threads_.close()", source)
        self.assertIn("retain_ack_timer(std::move(timer))", source)
        retain = source.split("void CanBridgeNode::retain_ack_timer", 1)[1].split(
            "void CanBridgeNode::on_planner_command", 1
        )[0]
        self.assertLess(retain.index("is_canceled()"), retain.index("push_back"))
        self.assertIn(
            "ai_robot_runtime_interfaces::ReapingThreadGroup ack_threads_", header
        )


if __name__ == "__main__":
    unittest.main()
