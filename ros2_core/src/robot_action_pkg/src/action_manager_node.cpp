#include "robot_action_pkg/action_manager_node.hpp"

#include "ai_robot_runtime_interfaces/runtime_event_identity.hpp"

#include <algorithm>
#include <chrono>
#include <exception>
#include <functional>
#include <memory>
#include <sstream>
#include <string>
#include <thread>

namespace robot_action_pkg
{

ActionManagerNode::ActionManagerNode()
: Node("action_manager_node")
{
  command_topic_ = this->declare_parameter<std::string>("command_topic", "/planner/command");
  result_topic_ =
    this->declare_parameter<std::string>("result_topic", "/action_manager/command_result");
  action_name_ = this->declare_parameter<std::string>("action_name", "/robot_command");
  action_delay_ms_ = this->declare_parameter<int64_t>("action_delay_ms", 100);
  feedback_period_ms_ = this->declare_parameter<int64_t>("feedback_period_ms", 50);
  goal_timeout_ms_ = this->declare_parameter<int64_t>("goal_timeout_ms", 0);
  runtime_event_enabled_ = this->declare_parameter<bool>("runtime_event_enabled", true);

  if (command_topic_.empty()) {
    RCLCPP_WARN(this->get_logger(), "command_topic is empty; using /planner/command");
    command_topic_ = "/planner/command";
  }
  if (result_topic_.empty()) {
    RCLCPP_WARN(
      this->get_logger(),
      "result_topic is empty; using /action_manager/command_result");
    result_topic_ = "/action_manager/command_result";
  }
  if (action_name_.empty()) {
    RCLCPP_WARN(this->get_logger(), "action_name is empty; using /robot_command");
    action_name_ = "/robot_command";
  }
  if (action_delay_ms_ < 0) {
    RCLCPP_WARN(this->get_logger(), "action_delay_ms must be non-negative; using 100 ms");
    action_delay_ms_ = 100;
  }
  if (feedback_period_ms_ < 1) {
    feedback_period_ms_ = 50;
  }
  if (goal_timeout_ms_ < 0) {
    RCLCPP_WARN(this->get_logger(), "goal_timeout_ms must be non-negative; disabling timeout");
    goal_timeout_ms_ = 0;
  }

  if (runtime_event_enabled_) {
    event_publisher_ = this->create_publisher<RuntimeEvent>("/runtime/events", rclcpp::QoS(10));
  }
  result_publisher_ = this->create_publisher<PlannerCommand>(result_topic_, rclcpp::QoS(10));

  action_server_ = rclcpp_action::create_server<RobotCommand>(
    this,
    action_name_,
    std::bind(&ActionManagerNode::handle_goal, this, std::placeholders::_1, std::placeholders::_2),
    std::bind(&ActionManagerNode::handle_cancel, this, std::placeholders::_1),
    std::bind(&ActionManagerNode::handle_accepted, this, std::placeholders::_1));
  action_client_ = rclcpp_action::create_client<RobotCommand>(this, action_name_);

  command_subscription_ = this->create_subscription<PlannerCommand>(
    command_topic_,
    rclcpp::QoS(10),
    std::bind(&ActionManagerNode::on_planner_command, this, std::placeholders::_1));

  RCLCPP_INFO(
    this->get_logger(),
    "action_manager_node subscribed to %s, action=%s, publishing result topic=%s, "
    "action_delay_ms=%ld goal_timeout_ms=%ld runtime_event_enabled=%s",
    command_topic_.c_str(),
    action_name_.c_str(),
    result_topic_.c_str(),
    action_delay_ms_,
    goal_timeout_ms_,
    runtime_event_enabled_ ? "true" : "false");
}

ActionManagerNode::~ActionManagerNode()
{
  shutting_down_.store(true);
  action_client_.reset();
  action_server_.reset();
  std::lock_guard<std::mutex> lock(goal_threads_mutex_);
  for (auto & thread : goal_threads_) {
    if (thread.joinable()) {
      thread.join();
    }
  }
}

void ActionManagerNode::on_planner_command(const PlannerCommand::SharedPtr command)
{
  publish_event(*command, "action_command_received", "action_receive", "received");
  publish_event(*command, "action_goal_received", "action_goal_received", "received");

  if (!action_client_->wait_for_action_server(std::chrono::milliseconds(100))) {
    publish_event(
      *command,
      "action_goal_rejected",
      "action_goal_rejected",
      "rejected",
      "action server unavailable");
    RCLCPP_ERROR(this->get_logger(), "action server %s is unavailable", action_name_.c_str());
    return;
  }

  auto command_copy = std::make_shared<PlannerCommand>(*command);
  auto goal = make_goal(*command);
  auto send_goal_options = rclcpp_action::Client<RobotCommand>::SendGoalOptions();
  send_goal_options.goal_response_callback =
    [this, command_copy](const rclcpp_action::ClientGoalHandle<RobotCommand>::SharedPtr & goal_handle) {
      if (!goal_handle) {
        publish_event(
          *command_copy,
          "action_goal_rejected",
          "action_goal_rejected",
          "rejected",
          "goal rejected by server");
        return;
      }
      publish_event(*command_copy, "action_goal_accepted", "action_goal_accepted", "accepted");
    };
  send_goal_options.feedback_callback =
    [this, command_copy](
      rclcpp_action::ClientGoalHandle<RobotCommand>::SharedPtr,
      const std::shared_ptr<const RobotCommand::Feedback> feedback) {
      publish_event(
        *command_copy,
        "action_feedback",
        "action_feedback",
        feedback->status,
        "feedback");
    };
  send_goal_options.result_callback =
    [this, command_copy](const rclcpp_action::ClientGoalHandle<RobotCommand>::WrappedResult & result) {
      if (
        result.result && result.code == rclcpp_action::ResultCode::SUCCEEDED &&
        result.result->success) {
        publish_event(
          *command_copy,
          "action_result",
          "action_result",
          "success",
          result.result->message);
        publish_result_command(*command_copy, *result.result);
        return;
      }

      std::string detail = "action failed";
      if (result.result) {
        detail = result.result->message;
      }
      publish_event(*command_copy, "action_result_failed", "action_result_failed", "failed", detail);
    };

  publish_event(*command, "action_goal_sent", "action_goal_sent", "sent");
  action_client_->async_send_goal(goal, send_goal_options);
}

rclcpp_action::GoalResponse ActionManagerNode::handle_goal(
  const rclcpp_action::GoalUUID & uuid,
  std::shared_ptr<const RobotCommand::Goal> goal)
{
  (void)uuid;
  const auto command = command_from_goal(*goal);
  publish_event(command, "action_server_goal_received", "action_server_goal_received", "accepted");
  return rclcpp_action::GoalResponse::ACCEPT_AND_EXECUTE;
}

rclcpp_action::CancelResponse ActionManagerNode::handle_cancel(
  const std::shared_ptr<GoalHandleRobotCommand> goal_handle)
{
  const auto command = command_from_goal(*goal_handle->get_goal());
  publish_event(command, "action_cancel_requested", "action_cancel_requested", "cancel_requested");
  return rclcpp_action::CancelResponse::ACCEPT;
}

void ActionManagerNode::handle_accepted(
  const std::shared_ptr<GoalHandleRobotCommand> goal_handle)
{
  if (!rclcpp::ok() || shutting_down_.load()) {
    return;
  }
  std::lock_guard<std::mutex> lock(goal_threads_mutex_);
  goal_threads_.emplace_back([this, goal_handle]() { execute_goal(goal_handle); });
}

void ActionManagerNode::execute_goal(const std::shared_ptr<GoalHandleRobotCommand> goal_handle)
{
  try {
    if (!rclcpp::ok() || shutting_down_.load()) {
      return;
    }
    const auto goal = goal_handle->get_goal();
    const auto command = command_from_goal(*goal);
    const auto start_timestamp_ns = steady_now_ns();
    publish_event(command, "action_execute_start", "action_execute_start", "executing");

    int64_t elapsed_ms = 0;
    while (elapsed_ms < action_delay_ms_) {
      if (!rclcpp::ok() || shutting_down_.load()) {
        return;
      }
      if (goal_handle->is_canceling()) {
        auto result = std::make_shared<RobotCommand::Result>();
        result->success = false;
        result->message = "goal cancelled";
        result->start_timestamp_ns = start_timestamp_ns;
        result->end_timestamp_ns = steady_now_ns();
        publish_event(command, "action_cancelled", "action_cancelled", "cancelled");
        goal_handle->canceled(result);
        return;
      }

      if (goal_timeout_ms_ > 0 && elapsed_ms >= goal_timeout_ms_) {
        auto result = std::make_shared<RobotCommand::Result>();
        result->success = false;
        result->message = "goal timeout";
        result->start_timestamp_ns = start_timestamp_ns;
        result->end_timestamp_ns = steady_now_ns();
        publish_event(command, "action_goal_timeout", "action_goal_timeout", "timeout");
        goal_handle->abort(result);
        return;
      }

      auto feedback = std::make_shared<RobotCommand::Feedback>();
      feedback->status = "executing";
      feedback->timestamp_ns = steady_now_ns();
      goal_handle->publish_feedback(feedback);

      const auto sleep_ms =
        std::min<int64_t>(feedback_period_ms_, action_delay_ms_ - elapsed_ms);
      std::this_thread::sleep_for(std::chrono::milliseconds(sleep_ms));
      elapsed_ms += sleep_ms;
    }

    if (!rclcpp::ok() || shutting_down_.load()) {
      return;
    }
    auto result = std::make_shared<RobotCommand::Result>();
    result->success = true;
    result->message = "action completed";
    result->start_timestamp_ns = start_timestamp_ns;
    result->end_timestamp_ns = steady_now_ns();
    publish_event(command, "action_execute_end", "action_execute_end", "success");
    goal_handle->succeed(result);
  } catch (const std::exception & error) {
    if (rclcpp::ok() && !shutting_down_.load()) {
      throw;
    }
    RCLCPP_DEBUG(
      this->get_logger(), "goal worker stopped during ROS shutdown: %s", error.what());
  }
}

void ActionManagerNode::publish_result_command(
  const PlannerCommand & command,
  const RobotCommand::Result & result) const
{
  PlannerCommand result_command = command;
  result_command.header.source_node = this->get_name();
  result_command.header.stage = "action_result";
  result_command.header.timestamp_ns = result.end_timestamp_ns > 0 ? result.end_timestamp_ns : steady_now_ns();
  result_command.confidence = result.success ? command.confidence : 0.0F;
  result_command.reason = result.message;
  result_publisher_->publish(result_command);
}

void ActionManagerNode::publish_event(
  const PlannerCommand & command,
  const std::string & event_name,
  const std::string & stage,
  const std::string & status,
  const std::string & detail) const
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
  event.event_type = "action_manager";
  ai_robot_runtime_interfaces::populate_runtime_identity(
    event, "monotonic", status.empty() ? "observed" : status);
  event.extra_json = make_extra_json(command, status, detail);
  event_publisher_->publish(event);
}

ActionManagerNode::RobotCommand::Goal ActionManagerNode::make_goal(
  const PlannerCommand & command) const
{
  RobotCommand::Goal goal;
  goal.header = command.header;
  goal.header.source_node = this->get_name();
  goal.header.stage = "action_goal";
  goal.header.timestamp_ns = steady_now_ns();
  goal.action = command.action;
  goal.target = command.target;
  goal.speed = command.speed;
  return goal;
}

ActionManagerNode::PlannerCommand ActionManagerNode::command_from_goal(
  const RobotCommand::Goal & goal) const
{
  PlannerCommand command;
  command.header = goal.header;
  command.action = goal.action;
  command.target = goal.target;
  command.speed = goal.speed;
  command.confidence = 1.0F;
  command.reason = "robot command goal";
  return command;
}

std::string ActionManagerNode::make_extra_json(
  const PlannerCommand & command,
  const std::string & status,
  const std::string & detail) const
{
  std::ostringstream stream;
  stream << "{\"action\":\"" << escape_json(command.action)
         << "\",\"target\":\"" << escape_json(command.target)
         << "\",\"speed\":" << command.speed
         << ",\"action_name\":\"" << escape_json(action_name_)
         << "\",\"result_topic\":\"" << escape_json(result_topic_)
         << "\",\"action_delay_ms\":" << action_delay_ms_
         << ",\"feedback_period_ms\":" << feedback_period_ms_
         << ",\"goal_timeout_ms\":" << goal_timeout_ms_;
  if (!status.empty()) {
    stream << ",\"status\":\"" << escape_json(status) << "\"";
  }
  if (!detail.empty()) {
    stream << ",\"detail\":\"" << escape_json(detail) << "\"";
  }
  stream << "}";
  return stream.str();
}

int64_t ActionManagerNode::steady_now_ns()
{
  const auto now = std::chrono::steady_clock::now().time_since_epoch();
  return std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
}

std::string ActionManagerNode::escape_json(const std::string & value)
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
  rclcpp::spin(std::make_shared<robot_action_pkg::ActionManagerNode>());
  rclcpp::shutdown();
  return 0;
}
