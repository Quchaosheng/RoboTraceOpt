#include <algorithm>
#include <chrono>
#include <memory>
#include <string>

#include "minimal_runtime_demo/common.hpp"
#include "rclcpp/rclcpp.hpp"
#include "ai_robot_runtime_interfaces/msg/runtime_event.hpp"
#include "std_msgs/msg/string.hpp"

namespace
{

class InputNode : public rclcpp::Node
{
public:
  InputNode()
  : Node("input_node")
  {
    input_rate_hz_ = this->declare_parameter<double>("input_rate_hz", 1.0);
    input_rate_hz_ = std::max(0.001, input_rate_hz_);

    runtime_event_pub_ = this->create_publisher<ai_robot_runtime_interfaces::msg::RuntimeEvent>(
      "/runtime/events", rclcpp::QoS(100));
    output_pub_ = this->create_publisher<std_msgs::msg::String>("/demo/input", rclcpp::QoS(10));

    const auto period_ms = std::max<int64_t>(1, static_cast<int64_t>(1000.0 / input_rate_hz_));
    timer_ = this->create_wall_timer(
      std::chrono::milliseconds(period_ms),
      [this]() { publish_input(); });

    RCLCPP_INFO(this->get_logger(), "input_node started. rate=%.3f Hz", input_rate_hz_);
  }

private:
  void publish_input()
  {
    ++sequence_id_;
    const auto trace_id = minimal_runtime_demo::make_trace_id(sequence_id_);
    const auto timestamp_ns = minimal_runtime_demo::get_timestamp_ns();

    runtime_event_pub_->publish(minimal_runtime_demo::make_runtime_event(
      trace_id, sequence_id_, this->get_name(), "input_publish", timestamp_ns));

    std_msgs::msg::String msg;
    msg.data = minimal_runtime_demo::make_demo_payload(trace_id, sequence_id_, timestamp_ns);
    output_pub_->publish(msg);
  }

  double input_rate_hz_;
  uint64_t sequence_id_{0};
  rclcpp::TimerBase::SharedPtr timer_;
  rclcpp::Publisher<ai_robot_runtime_interfaces::msg::RuntimeEvent>::SharedPtr runtime_event_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr output_pub_;
};

}  // namespace

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<InputNode>());
  rclcpp::shutdown();
  return 0;
}
