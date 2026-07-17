#include "runtime_logger_pkg/runtime_event_logger_node.hpp"

#include <filesystem>
#include <functional>
#include <iomanip>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>

namespace runtime_logger_pkg
{

RuntimeEventLoggerNode::RuntimeEventLoggerNode()
: Node("runtime_event_logger_node")
{
  output_path_ = this->declare_parameter<std::string>("output_path", "logs/runtime_events.jsonl");
  flush_every_event_ = this->declare_parameter<bool>("flush_every_event", false);

  open_output_file();

  event_subscription_ = this->create_subscription<RuntimeEvent>(
    "/runtime/events",
    rclcpp::QoS(100),
    std::bind(&RuntimeEventLoggerNode::on_runtime_event, this, std::placeholders::_1));

  RCLCPP_INFO(
    this->get_logger(),
    "runtime_event_logger_node logging /runtime/events to %s flush_every_event=%s",
    output_path_.c_str(),
    flush_every_event_ ? "true" : "false");
}

RuntimeEventLoggerNode::~RuntimeEventLoggerNode()
{
  std::lock_guard<std::mutex> lock(output_mutex_);
  if (output_stream_.is_open()) {
    output_stream_.flush();
    output_stream_.close();
  }
}

void RuntimeEventLoggerNode::open_output_file()
{
  const std::filesystem::path output_path(output_path_);
  const auto parent_path = output_path.parent_path();

  if (!parent_path.empty()) {
    std::error_code error;
    std::filesystem::create_directories(parent_path, error);
    if (error) {
      throw std::runtime_error(
        "failed to create log directory " + parent_path.string() + ": " + error.message());
    }
  }

  output_stream_.open(output_path_, std::ios::out | std::ios::app);
  if (!output_stream_.is_open()) {
    throw std::runtime_error("failed to open runtime event log file: " + output_path_);
  }
}

void RuntimeEventLoggerNode::on_runtime_event(const RuntimeEvent::SharedPtr event)
{
  const auto line = event_to_json_line(*event);

  std::lock_guard<std::mutex> lock(output_mutex_);
  output_stream_ << line << '\n';
  if (flush_every_event_) {
    output_stream_.flush();
  }
}

std::string RuntimeEventLoggerNode::event_to_json_line(const RuntimeEvent & event)
{
  std::ostringstream stream;
  stream << "{\"trace_id\":\"" << escape_json(event.header.trace_id)
         << "\",\"oracle_id\":\"" << escape_json(event.header.oracle_id)
         << "\",\"sequence_id\":" << event.header.sequence_id
         << ",\"source_node\":\"" << escape_json(event.header.source_node)
         << "\",\"stage\":\"" << escape_json(event.header.stage)
         << "\",\"timestamp_ns\":" << event.header.timestamp_ns
         << ",\"event_name\":\"" << escape_json(event.event_name)
         << "\",\"event_type\":\"" << escape_json(event.event_type)
         << "\",\"pid\":" << event.pid
         << ",\"tid\":" << event.tid
         << ",\"host_id\":\"" << escape_json(event.host_id)
         << "\",\"clock_id\":\"" << escape_json(event.clock_id)
         << "\",\"duration_ns\":" << event.duration_ns
         << ",\"status\":\"" << escape_json(event.status)
         << "\",\"reason_code\":\"" << escape_json(event.reason_code)
         << "\",\"extra_json\":\"" << escape_json(event.extra_json)
         << "\"}";
  return stream.str();
}

std::string RuntimeEventLoggerNode::escape_json(const std::string & value)
{
  std::ostringstream stream;
  for (const unsigned char character : value) {
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
      case '\b':
        stream << "\\b";
        break;
      case '\f':
        stream << "\\f";
        break;
      default:
        if (character < 0x20) {
          stream << "\\u"
                 << std::hex << std::setw(4) << std::setfill('0')
                 << static_cast<int>(character)
                 << std::dec << std::setfill(' ');
        } else {
          stream << character;
        }
        break;
    }
  }
  return stream.str();
}

}  // namespace runtime_logger_pkg

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<runtime_logger_pkg::RuntimeEventLoggerNode>());
  rclcpp::shutdown();
  return 0;
}
