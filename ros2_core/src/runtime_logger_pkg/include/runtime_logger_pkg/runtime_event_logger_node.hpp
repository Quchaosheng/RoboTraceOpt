#ifndef RUNTIME_LOGGER_PKG_RUNTIME_EVENT_LOGGER_NODE_HPP_
#define RUNTIME_LOGGER_PKG_RUNTIME_EVENT_LOGGER_NODE_HPP_

#include <fstream>
#include <mutex>
#include <string>

#include "ai_robot_runtime_interfaces/msg/runtime_event.hpp"
#include "rclcpp/rclcpp.hpp"

namespace runtime_logger_pkg
{

class RuntimeEventLoggerNode final : public rclcpp::Node
{
public:
  RuntimeEventLoggerNode();
  ~RuntimeEventLoggerNode() override;

private:
  using RuntimeEvent = ai_robot_runtime_interfaces::msg::RuntimeEvent;

  void on_runtime_event(const RuntimeEvent::SharedPtr event);
  void open_output_file();

  static std::string event_to_json_line(const RuntimeEvent & event);
  static std::string escape_json(const std::string & value);

  rclcpp::Subscription<RuntimeEvent>::SharedPtr event_subscription_;

  std::string output_path_{"logs/runtime_events.jsonl"};
  bool flush_every_event_{false};

  std::ofstream output_stream_;
  std::mutex output_mutex_;
};

}  // namespace runtime_logger_pkg

#endif  // RUNTIME_LOGGER_PKG_RUNTIME_EVENT_LOGGER_NODE_HPP_
