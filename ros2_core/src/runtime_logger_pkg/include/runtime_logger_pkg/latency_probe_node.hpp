#ifndef RUNTIME_LOGGER_PKG_LATENCY_PROBE_NODE_HPP_
#define RUNTIME_LOGGER_PKG_LATENCY_PROBE_NODE_HPP_

#include <cstddef>
#include <cstdint>
#include <fstream>
#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>

#include "ai_robot_runtime_interfaces/msg/planner_command.hpp"
#include "rclcpp/rclcpp.hpp"

namespace runtime_logger_pkg
{

class LatencyProbeNode final : public rclcpp::Node
{
public:
  LatencyProbeNode();
  ~LatencyProbeNode() override;

private:
  using PlannerCommand = ai_robot_runtime_interfaces::msg::PlannerCommand;

  struct PendingInput
  {
    std::string oracle_id;
    std::string stage;
    std::int64_t timestamp_ns{0};
  };

  struct PendingCompletion
  {
    std::string stage;
    std::int64_t timestamp_ns{0};
    bool send_success{false};
  };

  void on_input(const PlannerCommand::SharedPtr message);
  void on_completion(const PlannerCommand::SharedPtr message);
  void open_output_file();
  void write_sample_locked(
    const PlannerCommand & message,
    const PendingInput & input,
    const PendingCompletion & completion);
  void remember_completed_locked(const std::string & key);

  static std::string sample_key(const PlannerCommand & message);
  static std::string csv_field(const std::string & value);

  rclcpp::Subscription<PlannerCommand>::SharedPtr input_subscription_;
  rclcpp::Subscription<PlannerCommand>::SharedPtr completion_subscription_;

  std::string input_topic_{"/planner/command"};
  std::string completion_topic_{"/probe/can_frame_sent"};
  std::string output_path_{"logs/probe_latency.csv"};
  bool flush_every_sample_{false};
  std::size_t max_pending_samples_{4096};

  std::ofstream output_stream_;
  std::mutex mutex_;
  std::unordered_map<std::string, PendingInput> pending_inputs_;
  std::unordered_map<std::string, PendingCompletion> pending_completions_;
  std::unordered_set<std::string> completed_keys_;
};

}  // namespace runtime_logger_pkg

#endif  // RUNTIME_LOGGER_PKG_LATENCY_PROBE_NODE_HPP_
