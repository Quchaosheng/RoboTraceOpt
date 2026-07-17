#include "can_bridge_pkg/can_bridge_node.hpp"

#include "ai_robot_runtime_interfaces/runtime_event_identity.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cerrno>
#include <cstring>
#include <functional>
#include <iomanip>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <utility>

#include "rclcpp/exceptions/exceptions.hpp"

#ifdef __linux__
#include <linux/can.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace can_bridge_pkg
{

CanBridgeNode::CanBridgeNode()
: Node("can_bridge_node")
{
  command_topic_ = this->declare_parameter<std::string>("command_topic", "/planner/command");
  can_interface_ = this->declare_parameter<std::string>("can_interface", "vcan0");
  mock_mode_ = this->declare_parameter<bool>("mock_mode", true);
  ack_enabled_ = this->declare_parameter<bool>("ack_enabled", true);
  ack_mode_ = this->declare_parameter<std::string>("ack_mode", "mock");
  runtime_event_enabled_ = this->declare_parameter<bool>("runtime_event_enabled", true);
  probe_enabled_ = this->declare_parameter<bool>("probe_enabled", false);
  can_send_delay_ms_ = this->declare_parameter<int64_t>("can_send_delay_ms", 5);
  ack_timeout_ms_ = this->declare_parameter<int64_t>("ack_timeout_ms", 50);
  retry_backoff_ms_ = this->declare_parameter<int64_t>("retry_backoff_ms", 10);
  mock_ack_delay_ms_ = this->declare_parameter<int64_t>("mock_ack_delay_ms", 5);
  mock_ack_policy_ = this->declare_parameter<std::string>("mock_ack_policy", "success");
  ack_can_id_offset_ = this->declare_parameter<int64_t>("ack_can_id_offset", 0x80);
  const auto max_retries_param = this->declare_parameter<int64_t>("max_retries", 2);

  if (can_interface_.empty()) {
    RCLCPP_WARN(this->get_logger(), "can_interface is empty; using vcan0");
    can_interface_ = "vcan0";
  }
  if (command_topic_.empty()) {
    RCLCPP_WARN(this->get_logger(), "command_topic is empty; using /planner/command");
    command_topic_ = "/planner/command";
  }
  if (can_send_delay_ms_ < 0) {
    RCLCPP_WARN(this->get_logger(), "can_send_delay_ms must be non-negative; using 5 ms");
    can_send_delay_ms_ = 5;
  }
  if (ack_timeout_ms_ < 1) {
    RCLCPP_WARN(this->get_logger(), "ack_timeout_ms must be positive; using 50 ms");
    ack_timeout_ms_ = 50;
  }
  if (retry_backoff_ms_ < 0) {
    RCLCPP_WARN(this->get_logger(), "retry_backoff_ms must be non-negative; using 10 ms");
    retry_backoff_ms_ = 10;
  }
  if (mock_ack_delay_ms_ < 0) {
    RCLCPP_WARN(this->get_logger(), "mock_ack_delay_ms must be non-negative; using 5 ms");
    mock_ack_delay_ms_ = 5;
  }
  if (max_retries_param < 0) {
    RCLCPP_WARN(this->get_logger(), "max_retries must be non-negative; using 2");
    max_retries_ = 2;
  } else {
    max_retries_ = static_cast<uint32_t>(max_retries_param);
  }
  if (ack_mode_ != "mock" && ack_mode_ != "socketcan" && ack_mode_ != "disabled") {
    RCLCPP_WARN(this->get_logger(), "unsupported ack_mode=%s; using mock", ack_mode_.c_str());
    ack_mode_ = "mock";
  }
  if (ack_mode_ == "disabled") {
    ack_enabled_ = false;
  }
  if (
    mock_ack_policy_ != "success" && mock_ack_policy_ != "delayed" &&
    mock_ack_policy_ != "drop_first" && mock_ack_policy_ != "drop")
  {
    RCLCPP_WARN(
      this->get_logger(), "unsupported mock_ack_policy=%s; using success",
      mock_ack_policy_.c_str());
    mock_ack_policy_ = "success";
  }

  if (runtime_event_enabled_) {
    event_publisher_ = this->create_publisher<RuntimeEvent>("/runtime/events", rclcpp::QoS(10));
  }
  if (probe_enabled_) {
    probe_completion_publisher_ = this->create_publisher<PlannerCommand>(
      "/probe/can_frame_sent",
      rclcpp::QoS(100));
  }
  command_subscription_ = this->create_subscription<PlannerCommand>(
    command_topic_,
    rclcpp::QoS(10),
    std::bind(&CanBridgeNode::on_planner_command, this, std::placeholders::_1));

  RCLCPP_INFO(
    this->get_logger(),
    "can_bridge_node subscribed to %s, interface=%s mock_mode=%s delay=%ld ms "
    "ack_enabled=%s ack_mode=%s ack_timeout=%ld ms max_retries=%u mock_ack_policy=%s "
    "runtime_event_enabled=%s probe_enabled=%s",
    command_topic_.c_str(),
    can_interface_.c_str(),
    mock_mode_ ? "true" : "false",
    can_send_delay_ms_,
    ack_enabled_ ? "true" : "false",
    ack_mode_.c_str(),
    ack_timeout_ms_,
    max_retries_,
    mock_ack_policy_.c_str(),
    runtime_event_enabled_ ? "true" : "false",
    probe_enabled_ ? "true" : "false");
}

CanBridgeNode::~CanBridgeNode()
{
  shutting_down_.store(true);
  std::lock_guard<std::mutex> lock(ack_threads_mutex_);
  for (auto & thread : ack_threads_) {
    if (thread.joinable()) {
      thread.join();
    }
  }
}

void CanBridgeNode::on_planner_command(const PlannerCommand::SharedPtr command)
{
  if (!rclcpp::ok() || shutting_down_.load()) {
    return;
  }
  const auto frame = encode_command(*command);

  publish_event(*command, frame, "can_command_received", "can_receive", true, "pending");
  publish_event(*command, frame, "can_encode_start", "can_encode_start", true, "pending");
  publish_event(*command, frame, "can_encode_end", "can_encode_end", true, "pending");

  send_attempt(*command, frame, 0);
}

void CanBridgeNode::send_attempt(
  const PlannerCommand & command,
  const EncodedCanFrame & frame,
  const uint32_t retry_count)
{
  if (can_send_delay_ms_ > 0) {
    std::this_thread::sleep_for(std::chrono::milliseconds(can_send_delay_ms_));
  }
  if (!rclcpp::ok() || shutting_down_.load()) {
    return;
  }

  std::string send_detail;
  const bool send_success = send_frame(frame, &send_detail);
  publish_event(
    command,
    frame,
    "can_frame_sent",
    "can_frame_sent",
    send_success,
    send_detail,
    false,
    retry_count);
  publish_probe_completion(command, send_success);

  if (!send_success) {
    publish_event(
      command,
      frame,
      "can_frame_send_failed",
      "can_frame_send_failed",
      false,
      send_detail,
      false,
      retry_count,
      "send_failed");
    return;
  }

  if (!ack_enabled_) {
    return;
  }

  start_ack_wait(command, frame, retry_count);
}

void CanBridgeNode::publish_probe_completion(
  const PlannerCommand & command,
  const bool send_success) const
{
  if (!probe_enabled_ || !probe_completion_publisher_) {
    return;
  }

  PlannerCommand probe_message = command;
  probe_message.header.source_node = this->get_name();
  probe_message.header.stage = send_success ? "can_frame_sent" : "can_frame_send_failed";
  probe_message.header.timestamp_ns = steady_now_ns();
  probe_message.confidence = send_success ? 1.0F : 0.0F;
  probe_message.reason = send_success ? "probe can frame sent" : "probe can frame send failed";
  probe_completion_publisher_->publish(probe_message);
}

void CanBridgeNode::start_ack_wait(
  const PlannerCommand & command,
  const EncodedCanFrame & frame,
  const uint32_t retry_count)
{
  publish_event(
    command,
    frame,
    "can_ack_wait_start",
    "can_ack_wait_start",
    true,
    "waiting for ack",
    false,
    retry_count);

  if (ack_mode_ == "socketcan") {
    schedule_socketcan_ack_or_timeout(command, frame, retry_count);
    return;
  }

  schedule_mock_ack(command, frame, retry_count);
  schedule_ack_timeout(command, frame, retry_count);
}

void CanBridgeNode::schedule_socketcan_ack_or_timeout(
  const PlannerCommand & command,
  const EncodedCanFrame & frame,
  const uint32_t retry_count)
{
  std::lock_guard<std::mutex> lock(ack_threads_mutex_);
  ack_threads_.emplace_back([this, command, frame, retry_count]() {
    std::string ack_detail;
    const bool ack_received = wait_for_socketcan_ack(frame, &ack_detail);
    if (shutting_down_.load()) {
      return;
    }
    if (ack_received) {
      publish_event(
        command,
        frame,
        "can_ack_received",
        "can_ack_received",
        true,
        ack_detail,
        true,
        retry_count,
        "ack_received");
      return;
    }
    on_ack_timeout(command, frame, retry_count);
  });
}

bool CanBridgeNode::wait_for_socketcan_ack(
  const EncodedCanFrame & frame,
  std::string * detail) const
{
#ifdef __linux__
  const int socket_fd = ::socket(PF_CAN, SOCK_RAW, CAN_RAW);
  if (socket_fd < 0) {
    *detail = std::string("ack socket failed: ") + std::strerror(errno);
    RCLCPP_ERROR(this->get_logger(), "%s", detail->c_str());
    return false;
  }

  ifreq interface_request {};
  std::strncpy(interface_request.ifr_name, can_interface_.c_str(), IFNAMSIZ - 1);
  interface_request.ifr_name[IFNAMSIZ - 1] = '\0';

  if (::ioctl(socket_fd, SIOCGIFINDEX, &interface_request) < 0) {
    *detail = std::string("ack ioctl SIOCGIFINDEX failed: ") + std::strerror(errno);
    RCLCPP_ERROR(this->get_logger(), "%s", detail->c_str());
    ::close(socket_fd);
    return false;
  }

  sockaddr_can address {};
  address.can_family = AF_CAN;
  address.can_ifindex = interface_request.ifr_ifindex;

  if (::bind(socket_fd, reinterpret_cast<sockaddr *>(&address), sizeof(address)) < 0) {
    *detail = std::string("ack bind failed: ") + std::strerror(errno);
    RCLCPP_ERROR(this->get_logger(), "%s", detail->c_str());
    ::close(socket_fd);
    return false;
  }

  const auto expected_ack_id = static_cast<uint32_t>(frame.can_id + ack_can_id_offset_);
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(ack_timeout_ms_);

  while (!shutting_down_.load() && std::chrono::steady_clock::now() < deadline) {
    const auto now = std::chrono::steady_clock::now();
    const auto remaining = deadline - now;
    const auto remaining_us =
      std::chrono::duration_cast<std::chrono::microseconds>(remaining).count();
    timeval timeout {};
    timeout.tv_sec = static_cast<long>(remaining_us / 1000000);
    timeout.tv_usec = static_cast<long>(remaining_us % 1000000);

    fd_set read_fds;
    FD_ZERO(&read_fds);
    FD_SET(socket_fd, &read_fds);
    const int ready = ::select(socket_fd + 1, &read_fds, nullptr, nullptr, &timeout);
    if (ready < 0) {
      if (errno == EINTR) {
        continue;
      }
      *detail = std::string("ack select failed: ") + std::strerror(errno);
      RCLCPP_ERROR(this->get_logger(), "%s", detail->c_str());
      ::close(socket_fd);
      return false;
    }
    if (ready == 0) {
      break;
    }

    can_frame ack_frame {};
    const auto bytes_read = ::read(socket_fd, &ack_frame, sizeof(ack_frame));
    if (bytes_read != static_cast<ssize_t>(sizeof(ack_frame))) {
      continue;
    }
    const auto observed_id = static_cast<uint32_t>(ack_frame.can_id & CAN_EFF_MASK);
    if (observed_id != expected_ack_id) {
      continue;
    }
    const bool payload_matches =
      ack_frame.can_dlc == frame.payload.size() &&
      std::equal(frame.payload.begin(), frame.payload.end(), ack_frame.data);
    if (!payload_matches) {
      continue;
    }

    ::close(socket_fd);
    *detail = "socketcan ack received";
    return true;
  }

  ::close(socket_fd);
  *detail = "socketcan ack timeout";
  return false;
#else
  (void)frame;
  *detail = "SocketCAN ACK is only available on Linux";
  RCLCPP_ERROR(this->get_logger(), "%s", detail->c_str());
  return false;
#endif
}

void CanBridgeNode::schedule_mock_ack(
  const PlannerCommand & command,
  const EncodedCanFrame & frame,
  const uint32_t retry_count)
{
  if (!rclcpp::ok() || shutting_down_.load()) {
    return;
  }
  int64_t ack_delay_ms = mock_ack_delay_ms_;
  if (mock_ack_policy_ == "delayed") {
    ack_delay_ms = std::max<int64_t>(mock_ack_delay_ms_, ack_timeout_ms_ + 10);
  }
  if (!mock_ack_will_arrive(retry_count) || ack_delay_ms >= ack_timeout_ms_) {
    return;
  }

  auto fired = std::make_shared<std::atomic_bool>(false);
  auto timer_reference = std::make_shared<std::weak_ptr<rclcpp::TimerBase>>();
  try {
    auto timer = this->create_wall_timer(
      std::chrono::milliseconds(ack_delay_ms),
      [this, command, frame, retry_count, fired, timer_reference]() {
        if (auto timer = timer_reference->lock()) {
          timer->cancel();
        }
        if (
          fired->exchange(true) || !rclcpp::ok() || shutting_down_.load())
        {
          return;
        }
        try {
          publish_event(
            command,
            frame,
            "can_ack_received",
            "can_ack_received",
            true,
            "mock ack received",
            true,
            retry_count,
            "ack_received");
        } catch (const rclcpp::exceptions::RCLError & error) {
          if (rclcpp::ok() && !shutting_down_.load()) {
            throw;
          }
          RCLCPP_DEBUG(
            this->get_logger(), "mock ACK stopped during ROS shutdown: %s", error.what());
        }
      });
    *timer_reference = timer;
    ack_timers_.push_back(std::move(timer));
  } catch (const rclcpp::exceptions::RCLError & error) {
    if (rclcpp::ok() && !shutting_down_.load()) {
      throw;
    }
    RCLCPP_DEBUG(
      this->get_logger(), "mock ACK timer skipped during ROS shutdown: %s", error.what());
  }
}

void CanBridgeNode::schedule_ack_timeout(
  const PlannerCommand & command,
  const EncodedCanFrame & frame,
  const uint32_t retry_count)
{
  if (!rclcpp::ok() || shutting_down_.load()) {
    return;
  }
  if (ack_mode_ == "mock" && mock_ack_will_arrive(retry_count) && mock_ack_policy_ != "delayed") {
    return;
  }

  auto fired = std::make_shared<std::atomic_bool>(false);
  auto timer_reference = std::make_shared<std::weak_ptr<rclcpp::TimerBase>>();
  try {
    auto timer = this->create_wall_timer(
      std::chrono::milliseconds(ack_timeout_ms_),
      [this, command, frame, retry_count, fired, timer_reference]() {
        if (auto timer = timer_reference->lock()) {
          timer->cancel();
        }
        if (
          fired->exchange(true) || !rclcpp::ok() || shutting_down_.load())
        {
          return;
        }
        try {
          on_ack_timeout(command, frame, retry_count);
        } catch (const rclcpp::exceptions::RCLError & error) {
          if (rclcpp::ok() && !shutting_down_.load()) {
            throw;
          }
          RCLCPP_DEBUG(
            this->get_logger(), "ACK timeout stopped during ROS shutdown: %s", error.what());
        }
      });
    *timer_reference = timer;
    ack_timers_.push_back(std::move(timer));
  } catch (const rclcpp::exceptions::RCLError & error) {
    if (rclcpp::ok() && !shutting_down_.load()) {
      throw;
    }
    RCLCPP_DEBUG(
      this->get_logger(), "ACK timeout timer skipped during ROS shutdown: %s", error.what());
  }
}

bool CanBridgeNode::mock_ack_will_arrive(const uint32_t retry_count) const
{
  if (ack_mode_ != "mock") {
    return false;
  }
  if (mock_ack_policy_ == "drop") {
    return false;
  }
  if (mock_ack_policy_ == "drop_first" && retry_count == 0) {
    return false;
  }
  return true;
}

void CanBridgeNode::on_ack_timeout(
  const PlannerCommand & command,
  const EncodedCanFrame & frame,
  const uint32_t retry_count)
{
  publish_event(
    command,
    frame,
    "can_ack_timeout",
    "can_ack_timeout",
    true,
    "ack timeout",
    false,
    retry_count);

  if (retry_count >= max_retries_) {
    publish_event(
      command,
      frame,
      "can_retry_exhausted",
      "can_retry_exhausted",
      true,
      "max retries exhausted",
      false,
      retry_count,
      "retry_exhausted");
    return;
  }

  const uint32_t next_retry_count = retry_count + 1;
  publish_event(
    command,
    frame,
    "can_retry_scheduled",
    "can_retry_scheduled",
    true,
    "retry scheduled",
    false,
    next_retry_count,
    "retry_scheduled");

  if (retry_backoff_ms_ > 0) {
    std::this_thread::sleep_for(std::chrono::milliseconds(retry_backoff_ms_));
  }
  send_attempt(command, frame, next_retry_count);
}

CanBridgeNode::EncodedCanFrame CanBridgeNode::encode_command(
  const PlannerCommand & command) const
{
  EncodedCanFrame frame;
  frame.can_id = 0x100u | (hash_string(command.action + ":" + command.target) & 0x7fu);

  const auto speed_milli = static_cast<uint16_t>(
    std::clamp<int32_t>(static_cast<int32_t>(std::lround(command.speed * 1000.0f)), 0, 65535));
  const auto sequence_low = static_cast<uint32_t>(command.header.sequence_id & 0xffffffffu);

  frame.payload[0] = static_cast<uint8_t>(hash_string(command.action) & 0xffu);
  frame.payload[1] = static_cast<uint8_t>(hash_string(command.target) & 0xffu);
  frame.payload[2] = static_cast<uint8_t>(speed_milli & 0xffu);
  frame.payload[3] = static_cast<uint8_t>((speed_milli >> 8) & 0xffu);
  frame.payload[4] = static_cast<uint8_t>(sequence_low & 0xffu);
  frame.payload[5] = static_cast<uint8_t>((sequence_low >> 8) & 0xffu);
  frame.payload[6] = static_cast<uint8_t>((sequence_low >> 16) & 0xffu);
  frame.payload[7] = static_cast<uint8_t>((sequence_low >> 24) & 0xffu);
  frame.payload_hex = payload_to_hex(frame.payload);

  return frame;
}

bool CanBridgeNode::send_frame(const EncodedCanFrame & frame, std::string * detail) const
{
  if (mock_mode_) {
    *detail = "mock frame logged";
    RCLCPP_INFO(
      this->get_logger(),
      "mock CAN send interface=%s can_id=%s payload_hex=%s",
      can_interface_.c_str(),
      can_id_to_hex(frame.can_id).c_str(),
      frame.payload_hex.c_str());
    return true;
  }

  return send_socketcan_frame(frame, detail);
}

bool CanBridgeNode::send_socketcan_frame(
  const EncodedCanFrame & frame,
  std::string * detail) const
{
#ifdef __linux__
  const int socket_fd = ::socket(PF_CAN, SOCK_RAW, CAN_RAW);
  if (socket_fd < 0) {
    *detail = std::string("socket failed: ") + std::strerror(errno);
    RCLCPP_ERROR(this->get_logger(), "%s", detail->c_str());
    return false;
  }

  ifreq interface_request {};
  std::strncpy(interface_request.ifr_name, can_interface_.c_str(), IFNAMSIZ - 1);
  interface_request.ifr_name[IFNAMSIZ - 1] = '\0';

  if (::ioctl(socket_fd, SIOCGIFINDEX, &interface_request) < 0) {
    *detail = std::string("ioctl SIOCGIFINDEX failed: ") + std::strerror(errno);
    RCLCPP_ERROR(this->get_logger(), "%s", detail->c_str());
    ::close(socket_fd);
    return false;
  }

  sockaddr_can address {};
  address.can_family = AF_CAN;
  address.can_ifindex = interface_request.ifr_ifindex;

  if (::bind(socket_fd, reinterpret_cast<sockaddr *>(&address), sizeof(address)) < 0) {
    *detail = std::string("bind failed: ") + std::strerror(errno);
    RCLCPP_ERROR(this->get_logger(), "%s", detail->c_str());
    ::close(socket_fd);
    return false;
  }

  can_frame socketcan_frame {};
  socketcan_frame.can_id = frame.can_id;
  socketcan_frame.can_dlc = static_cast<__u8>(frame.payload.size());
  std::copy(frame.payload.begin(), frame.payload.end(), socketcan_frame.data);

  const auto bytes_written = ::write(socket_fd, &socketcan_frame, sizeof(socketcan_frame));
  ::close(socket_fd);

  if (bytes_written != static_cast<ssize_t>(sizeof(socketcan_frame))) {
    *detail = std::string("write failed: ") + std::strerror(errno);
    RCLCPP_ERROR(this->get_logger(), "%s", detail->c_str());
    return false;
  }

  *detail = "socketcan frame sent";
  RCLCPP_INFO(
    this->get_logger(),
    "SocketCAN send interface=%s can_id=%s payload_hex=%s",
    can_interface_.c_str(),
    can_id_to_hex(frame.can_id).c_str(),
    frame.payload_hex.c_str());
  return true;
#else
  (void)frame;
  *detail = "SocketCAN is only available on Linux";
  RCLCPP_ERROR(this->get_logger(), "%s", detail->c_str());
  return false;
#endif
}

void CanBridgeNode::publish_event(
  const PlannerCommand & command,
  const EncodedCanFrame & frame,
    const std::string & event_name,
    const std::string & stage,
    const bool send_success,
    const std::string & send_detail,
    const bool ack_success,
    const uint32_t retry_count,
    const std::string & terminal_status) const
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
  event.event_type = "can_bridge";
  ai_robot_runtime_interfaces::populate_runtime_identity(
    event, "monotonic", terminal_status.empty() ? "observed" : terminal_status);
  event.extra_json = make_extra_json(
    command, frame, send_success, send_detail, ack_success, retry_count, terminal_status);
  event_publisher_->publish(event);
}

std::string CanBridgeNode::make_extra_json(
  const PlannerCommand & command,
  const EncodedCanFrame & frame,
  const bool send_success,
  const std::string & send_detail,
  const bool ack_success,
  const uint32_t retry_count,
  const std::string & terminal_status) const
{
  std::ostringstream stream;
  const auto ack_can_id = static_cast<uint32_t>(frame.can_id + ack_can_id_offset_);
  stream << "{\"action\":\"" << escape_json(command.action)
         << "\",\"target\":\"" << escape_json(command.target)
         << "\",\"speed\":" << command.speed
         << ",\"can_interface\":\"" << escape_json(can_interface_)
         << "\",\"mock_mode\":" << (mock_mode_ ? "true" : "false")
         << ",\"ack_enabled\":" << (ack_enabled_ ? "true" : "false")
         << ",\"ack_mode\":\"" << escape_json(ack_mode_)
         << "\",\"mock_ack_policy\":\"" << escape_json(mock_ack_policy_)
         << "\",\"ack_timeout_ms\":" << ack_timeout_ms_
         << ",\"retry_count\":" << retry_count
         << ",\"max_retries\":" << max_retries_
         << ",\"can_id\":\"" << can_id_to_hex(frame.can_id)
         << "\",\"ack_can_id\":\"" << can_id_to_hex(ack_can_id)
         << "\",\"payload_hex\":\"" << frame.payload_hex
         << "\",\"send_success\":" << (send_success ? "true" : "false")
         << ",\"ack_success\":" << (ack_success ? "true" : "false")
         << ",\"send_detail\":\"" << escape_json(send_detail)
         << "\"";
  if (!terminal_status.empty()) {
    stream << ",\"terminal_status\":\"" << escape_json(terminal_status) << "\"";
  }
  stream << "}";
  return stream.str();
}

int64_t CanBridgeNode::steady_now_ns()
{
  const auto now = std::chrono::steady_clock::now().time_since_epoch();
  return std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
}

uint32_t CanBridgeNode::hash_string(const std::string & value)
{
  uint32_t hash = 2166136261u;
  for (const auto character : value) {
    hash ^= static_cast<uint8_t>(character);
    hash *= 16777619u;
  }
  return hash;
}

std::string CanBridgeNode::can_id_to_hex(const uint32_t can_id)
{
  std::ostringstream stream;
  stream << "0x" << std::uppercase << std::hex << std::setw(3) << std::setfill('0') << can_id;
  return stream.str();
}

std::string CanBridgeNode::payload_to_hex(const std::array<uint8_t, 8> & payload)
{
  std::ostringstream stream;
  stream << std::uppercase << std::hex << std::setfill('0');
  for (const auto byte : payload) {
    stream << std::setw(2) << static_cast<int>(byte);
  }
  return stream.str();
}

std::string CanBridgeNode::escape_json(const std::string & value)
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

}  // namespace can_bridge_pkg

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<can_bridge_pkg::CanBridgeNode>());
  rclcpp::shutdown();
  return 0;
}
