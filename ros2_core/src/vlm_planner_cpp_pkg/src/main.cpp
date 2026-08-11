#include <exception>
#include <memory>

#include "rclcpp/rclcpp.hpp"
#include "vlm_planner_cpp_pkg/vlm_planner_node.hpp"

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  try {
    auto node = std::make_shared<vlm_planner_cpp_pkg::VlmPlannerNode>();
    if (node->executor_threads() == 1U) {
      rclcpp::executors::SingleThreadedExecutor executor;
      executor.add_node(node);
      executor.spin();
    } else {
      rclcpp::ExecutorOptions options;
      rclcpp::executors::MultiThreadedExecutor executor(
        options, node->executor_threads());
      executor.add_node(node);
      executor.spin();
    }
  } catch (const std::exception & error) {
    RCLCPP_FATAL(rclcpp::get_logger("vlm_planner_node"), "%s", error.what());
    rclcpp::shutdown();
    return 1;
  }
  rclcpp::shutdown();
  return 0;
}
