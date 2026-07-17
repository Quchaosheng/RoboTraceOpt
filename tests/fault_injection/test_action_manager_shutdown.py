import unittest
from pathlib import Path


class ActionManagerShutdownTest(unittest.TestCase):
    def test_goal_worker_exits_without_publishing_after_context_shutdown(self) -> None:
        source = (
            Path(__file__).resolve().parents[2]
            / "ros2_core"
            / "src"
            / "robot_action_pkg"
            / "src"
            / "action_manager_node.cpp"
        ).read_text(encoding="utf-8")

        execute_goal = source.split("void ActionManagerNode::execute_goal", 1)[1].split(
            "void ActionManagerNode::publish_result_command", 1
        )[0]
        self.assertGreaterEqual(
            execute_goal.count("if (!rclcpp::ok() || shutting_down_.load())"), 2
        )
        self.assertIn("catch (const std::exception & error)", execute_goal)
        self.assertIn("if (rclcpp::ok() && !shutting_down_.load())", execute_goal)
        self.assertIn("throw;", execute_goal)

    def test_goal_workers_are_owned_and_joined_by_the_node(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        source = (
            repository_root
            / "ros2_core"
            / "src"
            / "robot_action_pkg"
            / "src"
            / "action_manager_node.cpp"
        ).read_text(encoding="utf-8")
        header = (
            repository_root
            / "ros2_core"
            / "src"
            / "robot_action_pkg"
            / "include"
            / "robot_action_pkg"
            / "action_manager_node.hpp"
        ).read_text(encoding="utf-8")

        self.assertNotIn(".detach()", source)
        self.assertIn("goal_threads_.emplace_back", source)
        self.assertIn("thread.join()", source)
        destructor = source.split("ActionManagerNode::~ActionManagerNode()", 1)[1].split(
            "void ActionManagerNode::on_planner_command", 1
        )[0]
        self.assertLess(
            destructor.index("action_server_.reset()"),
            destructor.index("thread.join()"),
        )
        self.assertIn("std::vector<std::thread> goal_threads_", header)
        self.assertIn("std::atomic_bool shutting_down_", header)


if __name__ == "__main__":
    unittest.main()
