#pragma once

#include <cstdint>
#include <memory>
#include <string>

#include "ai_robot_runtime_interfaces/msg/camera_frame.hpp"
#include "ai_robot_runtime_interfaces/msg/planner_command.hpp"
#include "ai_robot_runtime_interfaces/msg/runtime_event.hpp"
#include "rclcpp/rclcpp.hpp"
#include "robotraceopt/planner/clients.hpp"
#include "robotraceopt/planner/model_admission.hpp"
#include "vlm_planner_cpp_pkg/runtime_contract.hpp"

namespace vlm_planner_cpp_pkg
{

class VlmPlannerNode final : public rclcpp::Node
{
public:
  explicit VlmPlannerNode(const rclcpp::NodeOptions & options = rclcpp::NodeOptions{});

  [[nodiscard]] std::size_t executor_threads() const noexcept;
  [[nodiscard]] const BackendSelection & backend_selection() const noexcept;

private:
  using CameraFrame = ai_robot_runtime_interfaces::msg::CameraFrame;
  using PlannerCommand = ai_robot_runtime_interfaces::msg::PlannerCommand;
  using RuntimeEvent = ai_robot_runtime_interfaces::msg::RuntimeEvent;
  using ModelRequest = robotraceopt::planner::ModelRequest;
  using ModelResult = robotraceopt::planner::ModelResult;
  using PlannerDecision = robotraceopt::planner::PlannerDecision;

  void on_camera_frame(const CameraFrame::SharedPtr frame);
  void run_executor_contention() const;
  [[nodiscard]] ModelRequest make_model_request(
    const CameraFrame & frame, std::int64_t now_ns) const;
  [[nodiscard]] ModelResult plan(const ModelRequest & request) const;
  [[nodiscard]] PlannerCommand make_command(
    const CameraFrame & frame, const PlannerDecision & decision) const;
  void reject_without_model(
    const CameraFrame & frame, const ModelRequest & request,
    const std::string & stage, const std::string & reason_code,
    std::int64_t started_ns);
  void publish_abstention(
    const CameraFrame & frame, const ModelRequest & request,
    const ModelResult & result, const std::string & reason_code,
    std::int64_t started_ns, std::int64_t finished_ns);
  void publish_event(
    const CameraFrame & frame, const std::string & stage,
    const ModelRequest & request, const ModelResult * result,
    const PlannerDecision * decision, const std::string & effective_backend,
    bool used_fallback, const std::string & fallback_reason,
    std::int64_t timestamp_ns = 0, std::int64_t duration_ns = 0,
    const std::string & status = "observed", const std::string & reason_code = "",
    const std::string & additional_fields = "") const;
  [[nodiscard]] std::string make_event_extra(
    const CameraFrame & frame, const ModelRequest & request,
    const ModelResult * result, const PlannerDecision * decision,
    const std::string & effective_backend, bool used_fallback,
    const std::string & fallback_reason, const std::string & additional_fields) const;

  static std::int64_t steady_now_ns();
  static std::string make_session_id();
  static std::string make_request_id(
    const std::string & session_id, const CameraFrame & frame);
  static std::string frame_fingerprint(const CameraFrame & frame);

  RuntimeSettings settings_;
  BackendSelection backend_selection_;
  std::string planner_mode_;
  bool runtime_events_enabled_{true};
  bool fallback_to_mock_{false};
  bool executor_contention_enabled_{false};
  std::int64_t executor_contention_period_ms_{25};
  std::int64_t executor_contention_load_ms_{0};
  std::int64_t observation_ttl_ms_{1000};
  std::int64_t observation_max_future_skew_ms_{100};
  std::int64_t model_dedup_window_ms_{10000};
  std::int64_t model_failure_window_ms_{30000};
  std::int64_t model_failure_storm_count_{3};
  std::string llm_provider_;
  std::string llm_api_style_;
  std::string llm_vision_mode_;
  std::string llm_model_;
  double llm_timeout_s_{3.0};
  std::string session_id_;

  robotraceopt::planner::MockPlannerClient mock_client_;
  std::unique_ptr<robotraceopt::planner::ModelAdmission> model_admission_;
  rclcpp::CallbackGroup::SharedPtr frame_callback_group_;
  rclcpp::CallbackGroup::SharedPtr contention_callback_group_;
  rclcpp::Publisher<PlannerCommand>::SharedPtr command_publisher_;
  rclcpp::Publisher<RuntimeEvent>::SharedPtr event_publisher_;
  rclcpp::Subscription<CameraFrame>::SharedPtr frame_subscription_;
  rclcpp::TimerBase::SharedPtr contention_timer_;
};

}  // namespace vlm_planner_cpp_pkg
