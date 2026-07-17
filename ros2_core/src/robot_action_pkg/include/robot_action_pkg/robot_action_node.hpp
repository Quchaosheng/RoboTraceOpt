#ifndef ROBOT_ACTION_PKG_ROBOT_ACTION_NODE_HPP_
#define ROBOT_ACTION_PKG_ROBOT_ACTION_NODE_HPP_

#include <cstdint>
#include <string>

#include "ai_robot_runtime_interfaces/msg/planner_command.hpp"
#include "ai_robot_runtime_interfaces/msg/runtime_event.hpp"
#include "rclcpp/rclcpp.hpp"

namespace robot_action_pkg
{

class RobotActionNode final : public rclcpp::Node
{
public:
  RobotActionNode();

private:
  using PlannerCommand = ai_robot_runtime_interfaces::msg::PlannerCommand;
  using RuntimeEvent = ai_robot_runtime_interfaces::msg::RuntimeEvent;

  void on_planner_command(const PlannerCommand::SharedPtr command);
  void publish_event(
    const PlannerCommand & command,
    const std::string & event_name,
    const std::string & stage) const;

  std::string make_extra_json(const PlannerCommand & command) const;

  static int64_t steady_now_ns();
  static std::string escape_json(const std::string & value);

  rclcpp::Subscription<PlannerCommand>::SharedPtr command_subscription_;
  rclcpp::Publisher<RuntimeEvent>::SharedPtr event_publisher_;

  int64_t action_delay_ms_{100};
  bool runtime_event_enabled_{true};
};

}  // namespace robot_action_pkg

#endif  // ROBOT_ACTION_PKG_ROBOT_ACTION_NODE_HPP_
