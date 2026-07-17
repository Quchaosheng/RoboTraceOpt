#include <chrono>
#include <memory>
#include <optional>
#include <string>
#include <thread>

#include "minimal_runtime_demo/common.hpp"
#include "rclcpp/rclcpp.hpp"
#include "ai_robot_runtime_interfaces/msg/runtime_event.hpp"
#include "std_msgs/msg/string.hpp"

namespace
{

class ActionNode : public rclcpp::Node
{
public:
  ActionNode()
  : Node("action_node")
  {
    action_delay_ms_ = this->declare_parameter<int>("action_delay_ms", 100);

    runtime_event_pub_ = this->create_publisher<ai_robot_runtime_interfaces::msg::RuntimeEvent>(
      "/runtime/events", rclcpp::QoS(100));
    output_pub_ = this->create_publisher<std_msgs::msg::String>(
      "/demo/action_output", rclcpp::QoS(10));
    input_sub_ = this->create_subscription<std_msgs::msg::String>(
      "/demo/planner_output",
      rclcpp::QoS(10),
      [this](const std_msgs::msg::String::SharedPtr msg) { handle_input(msg); });

    RCLCPP_INFO(this->get_logger(), "action_node started. delay=%d ms", action_delay_ms_);
  }

private:
  void publish_event(
    const minimal_runtime_demo::DemoPayload & payload,
    const std::string & stage)
  {
    runtime_event_pub_->publish(minimal_runtime_demo::make_runtime_event(
      payload.trace_id, payload.sequence_id, this->get_name(), stage));
  }

  void handle_input(const std_msgs::msg::String::SharedPtr msg)
  {
    const auto payload = minimal_runtime_demo::parse_demo_payload(msg->data);
    if (!payload.has_value()) {
      RCLCPP_WARN(
        this->get_logger(), "Failed to parse /demo/planner_output payload: %s", msg->data.c_str());
      return;
    }

    publish_event(*payload, "action_receive");
    publish_event(*payload, "action_start");
    std::this_thread::sleep_for(std::chrono::milliseconds(action_delay_ms_));
    publish_event(*payload, "action_end");
    publish_event(*payload, "action_publish");

    std_msgs::msg::String output;
    output.data = minimal_runtime_demo::make_demo_payload(
      payload->trace_id, payload->sequence_id, minimal_runtime_demo::get_timestamp_ns());
    output_pub_->publish(output);
  }

  int action_delay_ms_;
  rclcpp::Publisher<ai_robot_runtime_interfaces::msg::RuntimeEvent>::SharedPtr runtime_event_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr output_pub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr input_sub_;
};

}  // namespace

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<ActionNode>());
  rclcpp::shutdown();
  return 0;
}
