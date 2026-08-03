#include "camera_mock_pkg/camera_mock_node.hpp"

#include <algorithm>
#include <chrono>
#include <fstream>
#include <iomanip>
#include <iterator>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>

#include "ai_robot_runtime_interfaces/runtime_event_identity.hpp"

namespace camera_mock_pkg
{

CameraMockNode::CameraMockNode()
: Node("camera_mock_node")
{
  camera_rate_hz_ = this->declare_parameter<double>("camera_rate_hz", 1.0);
  const auto width_param = this->declare_parameter<int64_t>("width", 640);
  const auto height_param = this->declare_parameter<int64_t>("height", 480);
  const auto frame_payload_bytes =
    this->declare_parameter<int64_t>("frame_payload_bytes", 0);
  const auto frame_qos_depth = this->declare_parameter<int64_t>("frame_qos_depth", 10);
  const auto frame_qos_reliability =
    this->declare_parameter<std::string>("frame_qos_reliability", "reliable");
  image_file_ = this->declare_parameter<std::string>("image_file", "");
  fixed_trace_id_ = this->declare_parameter<std::string>("fixed_trace_id", "");
  fixed_oracle_id_ = this->declare_parameter<std::string>("fixed_oracle_id", "");
  const auto fixed_sequence_id = this->declare_parameter<int64_t>("fixed_sequence_id", 0);
  encoding_ = this->declare_parameter<std::string>("encoding", "mock");
  source_id_ = this->declare_parameter<std::string>("source_id", "camera_a");
  runtime_events_enabled_ = this->declare_parameter<bool>("runtime_events_enabled", true);

  if (camera_rate_hz_ <= 0.0) {
    RCLCPP_WARN(
      this->get_logger(),
      "camera_rate_hz must be positive; falling back to 1.0 Hz");
    camera_rate_hz_ = 1.0;
  }
  if (frame_payload_bytes < 0) {
    throw std::invalid_argument("frame_payload_bytes must be non-negative");
  }
  if (fixed_sequence_id < 0) {
    throw std::invalid_argument("fixed_sequence_id must be non-negative");
  }
  if (!image_file_.empty() && frame_payload_bytes != 0) {
    throw std::invalid_argument("image_file and frame_payload_bytes are mutually exclusive");
  }
  if (frame_qos_depth <= 0) {
    throw std::invalid_argument("frame_qos_depth must be positive");
  }

  width_ = static_cast<uint32_t>(std::max<int64_t>(width_param, 1));
  height_ = static_cast<uint32_t>(std::max<int64_t>(height_param, 1));
  frame_payload_bytes_ = static_cast<size_t>(frame_payload_bytes);
  fixed_sequence_id_ = static_cast<uint64_t>(fixed_sequence_id);
  if (!image_file_.empty()) {
    std::ifstream image_stream(image_file_, std::ios::binary);
    if (!image_stream.is_open()) {
      throw std::invalid_argument("image_file cannot be opened: " + image_file_);
    }
    fixed_frame_payload_.assign(
      std::istreambuf_iterator<char>(image_stream), std::istreambuf_iterator<char>());
    if (fixed_frame_payload_.empty()) {
      throw std::invalid_argument("image_file is empty: " + image_file_);
    }
    if (encoding_ != "jpeg" && encoding_ != "jpg" && encoding_ != "png" &&
      encoding_ != "webp")
    {
      throw std::invalid_argument("image_file requires jpeg, jpg, png, or webp encoding");
    }
  }
  if (source_id_.empty()) {
    source_id_ = this->get_name();
  }

  auto frame_qos = rclcpp::QoS(rclcpp::KeepLast(static_cast<size_t>(frame_qos_depth)));
  if (frame_qos_reliability == "reliable") {
    frame_qos.reliable();
  } else if (frame_qos_reliability == "best_effort") {
    frame_qos.best_effort();
  } else {
    throw std::invalid_argument("frame_qos_reliability must be reliable or best_effort");
  }
  frame_publisher_ = this->create_publisher<CameraFrame>("/camera/frame", frame_qos);
  event_publisher_ = this->create_publisher<RuntimeEvent>("/runtime/events", rclcpp::QoS(10));

  const auto timer_period = std::chrono::duration_cast<std::chrono::nanoseconds>(
    std::chrono::duration<double>(1.0 / camera_rate_hz_));
  timer_ = this->create_wall_timer(timer_period, [this]() { publish_frame(); });

  RCLCPP_INFO(
    this->get_logger(),
    "camera_mock_node publishing /camera/frame at %.3f Hz", camera_rate_hz_);
}

void CameraMockNode::publish_frame()
{
  const uint64_t sequence_id = ++sequence_id_;
  const int64_t frame_timestamp_ns = steady_now_ns();
  const uint64_t emitted_sequence_id = fixed_sequence_id_ == 0 ? sequence_id : fixed_sequence_id_;
  const std::string trace_id = fixed_trace_id_.empty() ?
    make_trace_id(emitted_sequence_id, frame_timestamp_ns) : fixed_trace_id_;
  const std::string oracle_id = fixed_oracle_id_.empty() ? make_oracle_id() : fixed_oracle_id_;

  CameraFrame frame;
  frame.header.trace_id = trace_id;
  frame.header.oracle_id = oracle_id;
  frame.header.sequence_id = emitted_sequence_id;
  frame.header.source_node = this->get_name();
  frame.header.stage = "camera_publish";
  frame.header.timestamp_ns = frame_timestamp_ns;
  frame.image_path = image_file_.empty() ?
    "fake_image_" + std::to_string(sequence_id) + ".jpg" : image_file_;
  frame.frame_id = static_cast<uint32_t>(emitted_sequence_id);
  frame.encoding = encoding_;
  frame.width = width_;
  frame.height = height_;
  if (fixed_frame_payload_.empty()) {
    frame.payload.assign(frame_payload_bytes_, static_cast<uint8_t>(sequence_id & 0xffU));
  } else {
    frame.payload = fixed_frame_payload_;
  }

  RuntimeEvent event;
  event.header = frame.header;
  event.header.timestamp_ns = frame_timestamp_ns;
  event.event_name = "camera_frame_published";
  event.event_type = "camera_publish";
  ai_robot_runtime_interfaces::populate_runtime_identity(event, "monotonic");
  event.extra_json = make_event_extra_json(frame);

  frame_publisher_->publish(frame);
  if (runtime_events_enabled_) {
    event_publisher_->publish(event);
  }
}

int64_t CameraMockNode::steady_now_ns()
{
  const auto now = std::chrono::steady_clock::now().time_since_epoch();
  return std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
}

std::string CameraMockNode::make_trace_id(
  const uint64_t sequence_id,
  const int64_t timestamp_ns) const
{
  std::ostringstream stream;
  stream << "trace_" << source_id_ << "_" << timestamp_ns << "_" << sequence_id;
  return stream.str();
}

std::string CameraMockNode::make_oracle_id()
{
  std::ostringstream stream;
  stream << "oracle_" << std::hex << std::setfill('0')
         << std::setw(16) << oracle_rng_()
         << std::setw(16) << oracle_rng_();
  return stream.str();
}

std::string CameraMockNode::make_event_extra_json(const CameraFrame & frame) const
{
  std::ostringstream stream;
  stream << "{\"image_path\":\"" << frame.image_path
         << "\",\"frame_id\":" << frame.frame_id
         << ",\"source_id\":\"" << source_id_ << "\""
         << ",\"width\":" << frame.width
         << ",\"height\":" << frame.height
         << ",\"encoding\":\"" << frame.encoding << "\""
         << ",\"payload_bytes\":" << frame.payload.size()
         << ",\"fixed_identity\":"
         << ((!fixed_trace_id_.empty() || !fixed_oracle_id_.empty() || fixed_sequence_id_ != 0) ? "true" : "false")
         << "}";
  return stream.str();
}

}  // namespace camera_mock_pkg

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<camera_mock_pkg::CameraMockNode>());
  rclcpp::shutdown();
  return 0;
}
