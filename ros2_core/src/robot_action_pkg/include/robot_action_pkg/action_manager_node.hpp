#ifndef ROBOT_ACTION_PKG_ACTION_MANAGER_NODE_HPP_
#define ROBOT_ACTION_PKG_ACTION_MANAGER_NODE_HPP_

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "ai_robot_runtime_interfaces/action/robot_command.hpp"
#include "ai_robot_runtime_interfaces/msg/planner_command.hpp"
#include "ai_robot_runtime_interfaces/msg/runtime_event.hpp"
#include "rclcpp/rclcpp.hpp"
#include "rclcpp_action/rclcpp_action.hpp"

namespace robot_action_pkg
{

class ActionManagerNode final : public rclcpp::Node
{
public:
  ActionManagerNode();
  ~ActionManagerNode() override;

private:
  using PlannerCommand = ai_robot_runtime_interfaces::msg::PlannerCommand;
  using RuntimeEvent = ai_robot_runtime_interfaces::msg::RuntimeEvent;
  using RobotCommand = ai_robot_runtime_interfaces::action::RobotCommand;
  using GoalHandleRobotCommand = rclcpp_action::ServerGoalHandle<RobotCommand>;

  void on_planner_command(const PlannerCommand::SharedPtr command);
  rclcpp_action::GoalResponse handle_goal(
    const rclcpp_action::GoalUUID & uuid,
    std::shared_ptr<const RobotCommand::Goal> goal);
  rclcpp_action::CancelResponse handle_cancel(
    const std::shared_ptr<GoalHandleRobotCommand> goal_handle);
  void handle_accepted(const std::shared_ptr<GoalHandleRobotCommand> goal_handle);
  void execute_goal(const std::shared_ptr<GoalHandleRobotCommand> goal_handle);

  void publish_result_command(
    const PlannerCommand & command,
    const RobotCommand::Result & result) const;
  void publish_event(
    const PlannerCommand & command,
    const std::string & event_name,
    const std::string & stage,
    const std::string & status = "",
    const std::string & detail = "") const;

  RobotCommand::Goal make_goal(const PlannerCommand & command) const;
  PlannerCommand command_from_goal(const RobotCommand::Goal & goal) const;
  std::string make_extra_json(
    const PlannerCommand & command,
    const std::string & status,
    const std::string & detail) const;

  static int64_t steady_now_ns();
  static std::string escape_json(const std::string & value);

  rclcpp::Subscription<PlannerCommand>::SharedPtr command_subscription_;
  rclcpp::Publisher<PlannerCommand>::SharedPtr result_publisher_;
  rclcpp::Publisher<RuntimeEvent>::SharedPtr event_publisher_;
  rclcpp_action::Server<RobotCommand>::SharedPtr action_server_;
  rclcpp_action::Client<RobotCommand>::SharedPtr action_client_;

  std::string command_topic_{"/planner/command"};
  std::string result_topic_{"/action_manager/command_result"};
  std::string action_name_{"/robot_command"};
  int64_t action_delay_ms_{100};
  int64_t feedback_period_ms_{50};
  int64_t goal_timeout_ms_{0};
  bool runtime_event_enabled_{true};
  std::atomic_bool shutting_down_{false};
  std::mutex goal_threads_mutex_;
  std::vector<std::thread> goal_threads_;
};

}  // namespace robot_action_pkg

#endif  // ROBOT_ACTION_PKG_ACTION_MANAGER_NODE_HPP_
