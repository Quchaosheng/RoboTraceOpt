#ifndef CAMERA_MOCK_PKG_CAMERA_MOCK_NODE_HPP_
#define CAMERA_MOCK_PKG_CAMERA_MOCK_NODE_HPP_

#include <cstddef>
#include <cstdint>
#include <random>
#include <string>

#include "ai_robot_runtime_interfaces/msg/camera_frame.hpp"
#include "ai_robot_runtime_interfaces/msg/runtime_event.hpp"
#include "rclcpp/rclcpp.hpp"

namespace camera_mock_pkg
{

class CameraMockNode final : public rclcpp::Node
{
public:
  CameraMockNode();

private:
  using CameraFrame = ai_robot_runtime_interfaces::msg::CameraFrame;
  using RuntimeEvent = ai_robot_runtime_interfaces::msg::RuntimeEvent;

  void publish_frame();
  static int64_t steady_now_ns();
  std::string make_trace_id(uint64_t sequence_id, int64_t timestamp_ns) const;
  std::string make_oracle_id();
  std::string make_event_extra_json(const CameraFrame & frame) const;

  rclcpp::Publisher<CameraFrame>::SharedPtr frame_publisher_;
  rclcpp::Publisher<RuntimeEvent>::SharedPtr event_publisher_;
  rclcpp::TimerBase::SharedPtr timer_;

  uint64_t sequence_id_{0};
  std::mt19937_64 oracle_rng_{std::random_device{}()};
  double camera_rate_hz_{1.0};
  uint32_t width_{640};
  uint32_t height_{480};
  size_t frame_payload_bytes_{0};
  std::string encoding_{"mock"};
  std::string source_id_{"camera_a"};
  bool runtime_events_enabled_{true};
};

}  // namespace camera_mock_pkg

#endif  // CAMERA_MOCK_PKG_CAMERA_MOCK_NODE_HPP_
