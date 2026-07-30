#include "runtime_logger_pkg/latency_probe_node.hpp"

#include <filesystem>
#include <functional>
#include <memory>
#include <stdexcept>
#include <utility>

namespace runtime_logger_pkg
{

LatencyProbeNode::LatencyProbeNode()
: Node("latency_probe_node")
{
  input_topic_ = declare_parameter<std::string>("input_topic", "/planner/command");
  completion_topic_ = declare_parameter<std::string>(
    "completion_topic", "/probe/can_frame_sent");
  output_path_ = declare_parameter<std::string>("output_path", "logs/probe_latency.csv");
  flush_every_sample_ = declare_parameter<bool>("flush_every_sample", false);
  const auto max_pending = declare_parameter<std::int64_t>("max_pending_samples", 4096);
  if (input_topic_.empty() || completion_topic_.empty() || output_path_.empty()) {
    throw std::invalid_argument("probe topics and output_path must not be empty");
  }
  if (max_pending < 1 || max_pending > 1000000) {
    throw std::invalid_argument("max_pending_samples must be in [1, 1000000]");
  }
  max_pending_samples_ = static_cast<std::size_t>(max_pending);

  open_output_file();
  input_subscription_ = create_subscription<PlannerCommand>(
    input_topic_, rclcpp::QoS(100),
    std::bind(&LatencyProbeNode::on_input, this, std::placeholders::_1));
  completion_subscription_ = create_subscription<PlannerCommand>(
    completion_topic_, rclcpp::QoS(100),
    std::bind(&LatencyProbeNode::on_completion, this, std::placeholders::_1));

  RCLCPP_INFO(
    get_logger(), "latency probe input=%s completion=%s output=%s max_pending=%zu",
    input_topic_.c_str(), completion_topic_.c_str(), output_path_.c_str(),
    max_pending_samples_);
}

LatencyProbeNode::~LatencyProbeNode()
{
  std::lock_guard<std::mutex> lock(mutex_);
  if (output_stream_.is_open()) {
    output_stream_.flush();
    output_stream_.close();
  }
}

void LatencyProbeNode::open_output_file()
{
  const std::filesystem::path output_path(output_path_);
  const auto parent_path = output_path.parent_path();
  if (!parent_path.empty()) {
    std::error_code error;
    std::filesystem::create_directories(parent_path, error);
    if (error) {
      throw std::runtime_error(
              "failed to create probe output directory " + parent_path.string() + ": " +
              error.message());
    }
  }

  std::error_code size_error;
  const bool write_header = !std::filesystem::exists(output_path) ||
    std::filesystem::file_size(output_path, size_error) == 0;
  if (size_error) {
    throw std::runtime_error("failed to inspect probe output file: " + size_error.message());
  }
  output_stream_.open(output_path_, std::ios::out | std::ios::app);
  if (!output_stream_.is_open()) {
    throw std::runtime_error("failed to open probe output file: " + output_path_);
  }
  if (write_header) {
    output_stream_ <<
      "trace_id,oracle_id,sequence_id,input_stage,completion_stage,start_timestamp_ns,"
      "end_timestamp_ns,latency_ns,send_success\n";
  }
}

void LatencyProbeNode::on_input(const PlannerCommand::SharedPtr message)
{
  if (message->header.trace_id.empty() || message->header.timestamp_ns <= 0) {
    RCLCPP_WARN(get_logger(), "ignoring probe input without trace identity or timestamp");
    return;
  }

  const auto key = sample_key(*message);
  std::lock_guard<std::mutex> lock(mutex_);
  if (completed_keys_.count(key) != 0) {
    return;
  }
  const auto completion = pending_completions_.find(key);
  const PendingInput input{
    message->header.oracle_id, message->header.stage, message->header.timestamp_ns};
  if (completion != pending_completions_.end()) {
    write_sample_locked(*message, input, completion->second);
    pending_completions_.erase(completion);
    remember_completed_locked(key);
    return;
  }
  if (pending_inputs_.size() >= max_pending_samples_) {
    pending_inputs_.erase(pending_inputs_.begin());
  }
  pending_inputs_[key] = input;
}

void LatencyProbeNode::on_completion(const PlannerCommand::SharedPtr message)
{
  if (message->header.trace_id.empty() || message->header.timestamp_ns <= 0) {
    RCLCPP_WARN(get_logger(), "ignoring probe completion without trace identity or timestamp");
    return;
  }

  const auto key = sample_key(*message);
  const PendingCompletion completion{
    message->header.stage, message->header.timestamp_ns,
    message->header.stage == "can_frame_sent"};
  std::lock_guard<std::mutex> lock(mutex_);
  if (completed_keys_.count(key) != 0) {
    return;
  }
  const auto input = pending_inputs_.find(key);
  if (input != pending_inputs_.end()) {
    write_sample_locked(*message, input->second, completion);
    pending_inputs_.erase(input);
    remember_completed_locked(key);
    return;
  }
  if (pending_completions_.size() >= max_pending_samples_) {
    pending_completions_.erase(pending_completions_.begin());
  }
  pending_completions_[key] = completion;
}

void LatencyProbeNode::write_sample_locked(
  const PlannerCommand & message,
  const PendingInput & input,
  const PendingCompletion & completion)
{
  if (completion.timestamp_ns < input.timestamp_ns) {
    RCLCPP_WARN(
      get_logger(), "ignoring negative probe latency trace_id=%s sequence_id=%lu",
      message.header.trace_id.c_str(), message.header.sequence_id);
    return;
  }
  const auto latency_ns = completion.timestamp_ns - input.timestamp_ns;
  output_stream_ << csv_field(message.header.trace_id) << ','
                 << csv_field(input.oracle_id) << ','
                 << message.header.sequence_id << ','
                 << csv_field(input.stage) << ','
                 << csv_field(completion.stage) << ','
                 << input.timestamp_ns << ','
                 << completion.timestamp_ns << ','
                 << latency_ns << ','
                 << (completion.send_success ? "true" : "false") << '\n';
  if (flush_every_sample_) {
    output_stream_.flush();
  }
}

void LatencyProbeNode::remember_completed_locked(const std::string & key)
{
  if (completed_keys_.size() >= max_pending_samples_) {
    completed_keys_.clear();
  }
  completed_keys_.insert(key);
}

std::string LatencyProbeNode::sample_key(const PlannerCommand & message)
{
  return message.header.trace_id + "\x1f" + std::to_string(message.header.sequence_id);
}

std::string LatencyProbeNode::csv_field(const std::string & value)
{
  if (value.find_first_of(",\"\r\n") == std::string::npos) {
    return value;
  }
  std::string escaped;
  escaped.reserve(value.size() + 2);
  escaped.push_back('"');
  for (const char character : value) {
    if (character == '"') {
      escaped.push_back('"');
    }
    escaped.push_back(character);
  }
  escaped.push_back('"');
  return escaped;
}

}  // namespace runtime_logger_pkg

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<runtime_logger_pkg::LatencyProbeNode>());
  rclcpp::shutdown();
  return 0;
}
