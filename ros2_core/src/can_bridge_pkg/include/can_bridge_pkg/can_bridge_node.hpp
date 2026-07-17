#ifndef CAN_BRIDGE_PKG_CAN_BRIDGE_NODE_HPP_
#define CAN_BRIDGE_PKG_CAN_BRIDGE_NODE_HPP_

#include <array>
#include <atomic>
#include <cstdint>
#include <mutex>
#include <thread>
#include <vector>
#include <string>

#include "ai_robot_runtime_interfaces/msg/planner_command.hpp"
#include "ai_robot_runtime_interfaces/msg/runtime_event.hpp"
#include "rclcpp/rclcpp.hpp"

namespace can_bridge_pkg
{

class CanBridgeNode final : public rclcpp::Node
{
public:
  CanBridgeNode();
  ~CanBridgeNode() override;

private:
  using PlannerCommand = ai_robot_runtime_interfaces::msg::PlannerCommand;
  using RuntimeEvent = ai_robot_runtime_interfaces::msg::RuntimeEvent;

  struct EncodedCanFrame
  {
    uint32_t can_id{0};
    std::array<uint8_t, 8> payload{};
    std::string payload_hex;
  };

  void on_planner_command(const PlannerCommand::SharedPtr command);
  EncodedCanFrame encode_command(const PlannerCommand & command) const;
  bool send_frame(const EncodedCanFrame & frame, std::string * detail) const;
  bool send_socketcan_frame(const EncodedCanFrame & frame, std::string * detail) const;
  void send_attempt(
    const PlannerCommand & command,
    const EncodedCanFrame & frame,
    uint32_t retry_count);
  void start_ack_wait(
    const PlannerCommand & command,
    const EncodedCanFrame & frame,
    uint32_t retry_count);
  void schedule_mock_ack(
    const PlannerCommand & command,
    const EncodedCanFrame & frame,
    uint32_t retry_count);
  void schedule_ack_timeout(
    const PlannerCommand & command,
    const EncodedCanFrame & frame,
    uint32_t retry_count);
  void schedule_socketcan_ack_or_timeout(
    const PlannerCommand & command,
    const EncodedCanFrame & frame,
    uint32_t retry_count);
  bool wait_for_socketcan_ack(
    const EncodedCanFrame & frame,
    std::string * detail) const;
  bool mock_ack_will_arrive(uint32_t retry_count) const;
  void on_ack_timeout(
    const PlannerCommand & command,
    const EncodedCanFrame & frame,
    uint32_t retry_count);
  void publish_event(
    const PlannerCommand & command,
    const EncodedCanFrame & frame,
    const std::string & event_name,
    const std::string & stage,
    bool send_success,
    const std::string & send_detail,
    bool ack_success = false,
    uint32_t retry_count = 0,
    const std::string & terminal_status = "") const;
  void publish_probe_completion(const PlannerCommand & command, bool send_success) const;

  std::string make_extra_json(
    const PlannerCommand & command,
    const EncodedCanFrame & frame,
    bool send_success,
    const std::string & send_detail,
    bool ack_success,
    uint32_t retry_count,
    const std::string & terminal_status) const;

  static int64_t steady_now_ns();
  static uint32_t hash_string(const std::string & value);
  static std::string can_id_to_hex(uint32_t can_id);
  static std::string payload_to_hex(const std::array<uint8_t, 8> & payload);
  static std::string escape_json(const std::string & value);

  rclcpp::Subscription<PlannerCommand>::SharedPtr command_subscription_;
  rclcpp::Publisher<RuntimeEvent>::SharedPtr event_publisher_;
  rclcpp::Publisher<PlannerCommand>::SharedPtr probe_completion_publisher_;

  std::string command_topic_{"/planner/command"};
  std::string can_interface_{"vcan0"};
  std::string ack_mode_{"mock"};
  std::string mock_ack_policy_{"success"};
  bool mock_mode_{true};
  bool ack_enabled_{true};
  bool runtime_event_enabled_{true};
  bool probe_enabled_{false};
  int64_t can_send_delay_ms_{5};
  int64_t ack_timeout_ms_{50};
  int64_t retry_backoff_ms_{10};
  int64_t mock_ack_delay_ms_{5};
  int64_t ack_can_id_offset_{0x80};
  uint32_t max_retries_{2};
  std::vector<rclcpp::TimerBase::SharedPtr> ack_timers_;
  std::vector<std::thread> ack_threads_;
  std::atomic_bool shutting_down_{false};
  std::mutex ack_threads_mutex_;
};

}  // namespace can_bridge_pkg

#endif  // CAN_BRIDGE_PKG_CAN_BRIDGE_NODE_HPP_
