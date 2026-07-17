#include "robot_action_pkg/robot_action_node.hpp"

#include <chrono>
#include <functional>
#include <memory>
#include <sstream>
#include <string>
#include <thread>

#include "ai_robot_runtime_interfaces/runtime_event_identity.hpp"

namespace robot_action_pkg
{

RobotActionNode::RobotActionNode()
: Node("robot_action_node")
{
  action_delay_ms_ = this->declare_parameter<int64_t>("action_delay_ms", 100);
  runtime_event_enabled_ = this->declare_parameter<bool>("runtime_event_enabled", true);
  if (action_delay_ms_ < 0) {
    RCLCPP_WARN(this->get_logger(), "action_delay_ms must be non-negative; using 100 ms");
    action_delay_ms_ = 100;
  }

  if (runtime_event_enabled_) {
    event_publisher_ = this->create_publisher<RuntimeEvent>("/runtime/events", rclcpp::QoS(10));
  }
  command_subscription_ = this->create_subscription<PlannerCommand>(
    "/planner/command",
    rclcpp::QoS(10),
    std::bind(&RobotActionNode::on_planner_command, this, std::placeholders::_1));

  RCLCPP_INFO(
    this->get_logger(),
    "robot_action_node subscribed to /planner/command with mock delay %ld ms "
    "runtime_event_enabled=%s",
    action_delay_ms_,
    runtime_event_enabled_ ? "true" : "false");
}

void RobotActionNode::on_planner_command(const PlannerCommand::SharedPtr command)
{
  publish_event(*command, "action_command_received", "action_receive");
  publish_event(*command, "action_execute_start", "action_execute_start");

  std::this_thread::sleep_for(std::chrono::milliseconds(action_delay_ms_));

  publish_event(*command, "action_execute_end", "action_execute_end");
}

void RobotActionNode::publish_event(
  const PlannerCommand & command,
  const std::string & event_name,
  const std::string & stage) const
{
  if (!runtime_event_enabled_ || !event_publisher_) {
    return;
  }
  RuntimeEvent event;
  event.header.trace_id = command.header.trace_id;
  event.header.oracle_id = command.header.oracle_id;
  event.header.sequence_id = command.header.sequence_id;
  event.header.source_node = this->get_name();
  event.header.stage = stage;
  event.header.timestamp_ns = steady_now_ns();
  event.event_name = event_name;
  event.event_type = "action";
  ai_robot_runtime_interfaces::populate_runtime_identity(event, "monotonic");
  event.extra_json = make_extra_json(command);
  event_publisher_->publish(event);
}

std::string RobotActionNode::make_extra_json(const PlannerCommand & command) const
{
  std::ostringstream stream;
  stream << "{\"action\":\"" << escape_json(command.action)
         << "\",\"target\":\"" << escape_json(command.target)
         << "\",\"speed\":" << command.speed
         << ",\"action_delay_ms\":" << action_delay_ms_
         << "}";
  return stream.str();
}

int64_t RobotActionNode::steady_now_ns()
{
  const auto now = std::chrono::steady_clock::now().time_since_epoch();
  return std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
}

std::string RobotActionNode::escape_json(const std::string & value)
{
  std::ostringstream stream;
  for (const char character : value) {
    switch (character) {
      case '\\':
        stream << "\\\\";
        break;
      case '"':
        stream << "\\\"";
        break;
      case '\n':
        stream << "\\n";
        break;
      case '\r':
        stream << "\\r";
        break;
      case '\t':
        stream << "\\t";
        break;
      default:
        stream << character;
        break;
    }
  }
  return stream.str();
}

}  // namespace robot_action_pkg

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<robot_action_pkg::RobotActionNode>());
  rclcpp::shutdown();
  return 0;
}
