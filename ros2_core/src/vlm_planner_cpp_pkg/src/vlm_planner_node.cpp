#include "vlm_planner_cpp_pkg/vlm_planner_node.hpp"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstdint>
#include <functional>
#include <iomanip>
#include <limits>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>

#include "ai_robot_runtime_interfaces/runtime_event_identity.hpp"
#include "robotraceopt/planner/model_contract.hpp"

namespace vlm_planner_cpp_pkg
{
namespace
{

constexpr std::int64_t kNanosecondsPerMillisecond = 1'000'000;
constexpr std::uint64_t kFnvOffset = 14695981039346656037ULL;
constexpr std::uint64_t kFnvPrime = 1099511628211ULL;

std::string quoted(const std::string & value)
{
  return "\"" + json_escape(value) + "\"";
}

const char * json_bool(const bool value)
{
  return value ? "true" : "false";
}

std::uint64_t fnv_update(std::uint64_t hash, const void * data, const std::size_t size)
{
  const auto * bytes = static_cast<const std::uint8_t *>(data);
  for (std::size_t index = 0; index < size; ++index) {
    hash ^= bytes[index];
    hash *= kFnvPrime;
  }
  return hash;
}

template<typename Value>
std::uint64_t fnv_value(std::uint64_t hash, const Value & value)
{
  return fnv_update(hash, &value, sizeof(value));
}

std::uint64_t fnv_string(std::uint64_t hash, const std::string & value)
{
  return fnv_update(hash, value.data(), value.size());
}

std::string hex_digest(const std::uint64_t value)
{
  std::ostringstream stream;
  stream << std::hex << std::setfill('0') << std::setw(16) << value;
  return stream.str();
}

std::int64_t saturating_deadline(const std::int64_t timestamp_ns, const std::int64_t ttl_ms)
{
  if (ttl_ms <= 0) {
    return 0;
  }
  if (ttl_ms > std::numeric_limits<std::int64_t>::max() / kNanosecondsPerMillisecond) {
    return std::numeric_limits<std::int64_t>::max();
  }
  const auto ttl_ns = ttl_ms * kNanosecondsPerMillisecond;
  if (timestamp_ns > std::numeric_limits<std::int64_t>::max() - ttl_ns) {
    return std::numeric_limits<std::int64_t>::max();
  }
  return timestamp_ns + ttl_ns;
}

std::string normalize(std::string value)
{
  std::transform(value.begin(), value.end(), value.begin(), [](const unsigned char character) {
      return static_cast<char>(std::tolower(character));
    });
  return value;
}

}  // namespace

VlmPlannerNode::VlmPlannerNode(const rclcpp::NodeOptions & options)
: Node("vlm_planner_node", options)
{
  const auto requested_backend = this->declare_parameter<std::string>("planner_backend", "mock");
  planner_mode_ = this->declare_parameter<std::string>("planner_mode", "mock");
  settings_.planner_delay_ms = this->declare_parameter<std::int64_t>("planner_delay_ms", 50);
  settings_.planner_delay_mode = normalize(
    this->declare_parameter<std::string>("planner_delay_mode", "sleep"));
  executor_contention_enabled_ =
    this->declare_parameter<bool>("executor_contention_enabled", false);
  executor_contention_period_ms_ =
    this->declare_parameter<std::int64_t>("executor_contention_period_ms", 25);
  executor_contention_load_ms_ =
    this->declare_parameter<std::int64_t>("executor_contention_load_ms", 0);
  settings_.executor_contention_period_ms = executor_contention_period_ms_;
  settings_.executor_contention_load_ms = executor_contention_load_ms_;
  settings_.executor_threads = this->declare_parameter<std::int64_t>("executor_threads", 1);
  const auto runtime_event_enabled =
    this->declare_parameter<bool>("runtime_event_enabled", true);
  const auto runtime_events_enabled_legacy =
    this->declare_parameter<bool>("runtime_events_enabled", true);
  runtime_events_enabled_ = runtime_event_enabled && runtime_events_enabled_legacy;
  settings_.frame_qos_depth = this->declare_parameter<std::int64_t>("frame_qos_depth", 10);
  settings_.frame_qos_reliability = normalize(
    this->declare_parameter<std::string>("frame_qos_reliability", "reliable"));

  llm_provider_ = this->declare_parameter<std::string>("llm_provider", "openai_compatible");
  static_cast<void>(this->declare_parameter<std::string>("llm_api_base", ""));
  static_cast<void>(this->declare_parameter<std::string>("llm_api_key_env", "LLM_API_KEY"));
  llm_model_ = this->declare_parameter<std::string>("llm_model", "");
  llm_timeout_s_ = this->declare_parameter<double>("llm_timeout_s", 3.0);
  llm_api_style_ = this->declare_parameter<std::string>("llm_api_style", "chat_completions");
  llm_vision_mode_ = this->declare_parameter<std::string>("llm_vision_mode", "metadata");
  const auto llm_max_image_bytes =
    this->declare_parameter<std::int64_t>("llm_max_image_bytes", 1'000'000);
  observation_ttl_ms_ = this->declare_parameter<std::int64_t>("observation_ttl_ms", 1000);
  settings_.observation_ttl_ms = observation_ttl_ms_;
  settings_.model_queue_delay_ms =
    this->declare_parameter<std::int64_t>("model_queue_delay_ms", 0);
  settings_.model_queue_delay_mode = normalize(
    this->declare_parameter<std::string>("model_queue_delay_mode", "sleep"));
  model_dedup_window_ms_ =
    this->declare_parameter<std::int64_t>("model_dedup_window_ms", 10000);
  observation_max_future_skew_ms_ =
    this->declare_parameter<std::int64_t>("observation_max_future_skew_ms", 100);
  model_failure_window_ms_ =
    this->declare_parameter<std::int64_t>("model_failure_window_ms", 30000);
  model_failure_storm_count_ =
    this->declare_parameter<std::int64_t>("model_failure_storm_count", 3);
  static_cast<void>(this->declare_parameter<std::string>("model_record_path", ""));
  static_cast<void>(this->declare_parameter<std::string>("model_replay_path", ""));
  fallback_to_mock_ = this->declare_parameter<bool>("fallback_to_mock", false);

  validate_runtime_settings(settings_);
  if (model_dedup_window_ms_ <= 0 || model_failure_window_ms_ <= 0 ||
    model_failure_storm_count_ <= 0)
  {
    throw std::invalid_argument("planner temporal windows and thresholds must be positive");
  }
  if (observation_max_future_skew_ms_ < 0) {
    throw std::invalid_argument("observation_max_future_skew_ms must be non-negative");
  }
  if (llm_timeout_s_ <= 0.0 || llm_max_image_bytes <= 0) {
    throw std::invalid_argument("LLM timeout and image limit must be positive");
  }
  backend_selection_ = select_backend(requested_backend);
  if (!planner_mode_.empty() && planner_mode_ != "mock") {
    RCLCPP_WARN(
      this->get_logger(),
      "planner_mode is deprecated and ignored; use planner_backend");
  }
  if (fallback_to_mock_ && backend_selection_.requested == "llm") {
    RCLCPP_WARN(
      this->get_logger(),
      "fallback_to_mock is deprecated and ignored; non-mock backends fail closed");
  }
  if (!backend_selection_.motion_enabled()) {
    RCLCPP_ERROR(
      this->get_logger(),
      "planner_backend=%s is unavailable in the C++ runtime (%s); entering fail-closed abstain mode",
      backend_selection_.requested.c_str(), backend_selection_.reason.c_str());
  }

  session_id_ = make_session_id();
  model_admission_ = std::make_unique<robotraceopt::planner::ModelAdmission>(
    model_dedup_window_ms_, model_failure_window_ms_,
    static_cast<std::size_t>(model_failure_storm_count_), observation_max_future_skew_ms_);

  frame_callback_group_ = this->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);
  contention_callback_group_ =
    this->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);
  command_publisher_ = this->create_publisher<PlannerCommand>("/planner/command", rclcpp::QoS(10));
  event_publisher_ = this->create_publisher<RuntimeEvent>("/runtime/events", rclcpp::QoS(10));

  auto frame_qos = rclcpp::QoS(rclcpp::KeepLast(
      static_cast<std::size_t>(settings_.frame_qos_depth))).durability_volatile();
  if (settings_.frame_qos_reliability == "reliable") {
    frame_qos.reliable();
  } else {
    frame_qos.best_effort();
  }
  rclcpp::SubscriptionOptions subscription_options;
  subscription_options.callback_group = frame_callback_group_;
  frame_subscription_ = this->create_subscription<CameraFrame>(
    "/camera/frame", frame_qos,
    std::bind(&VlmPlannerNode::on_camera_frame, this, std::placeholders::_1),
    subscription_options);

  if (executor_contention_enabled_) {
    contention_timer_ = this->create_wall_timer(
      std::chrono::milliseconds(executor_contention_period_ms_),
      std::bind(&VlmPlannerNode::run_executor_contention, this),
      contention_callback_group_);
  }

  RCLCPP_INFO(
    this->get_logger(),
    "vlm_planner_node C++ runtime active: requested_backend=%s active_backend=%s "
    "executor_threads=%zu",
    backend_selection_.requested.c_str(), backend_selection_.active.c_str(), executor_threads());
}

std::size_t VlmPlannerNode::executor_threads() const noexcept
{
  return static_cast<std::size_t>(settings_.executor_threads);
}

const BackendSelection & VlmPlannerNode::backend_selection() const noexcept
{
  return backend_selection_;
}

void VlmPlannerNode::on_camera_frame(const CameraFrame::SharedPtr frame)
{
  const auto started_ns = steady_now_ns();
  const auto request = make_model_request(*frame, started_ns);
  publish_event(
    *frame, "planner_receive", request, nullptr, nullptr,
    backend_selection_.active, false, "");

  const auto admission_reason = model_admission_->admit(request, started_ns);
  if (!admission_reason.empty()) {
    reject_without_model(
      *frame, request, "planner_request_rejected", admission_reason, started_ns);
    return;
  }

  std::ostringstream start_fields;
  start_fields << ",\"planner_delay_ms\":" << settings_.planner_delay_ms
               << ",\"planner_delay_mode\":" << quoted(settings_.planner_delay_mode)
               << ",\"model_queue_delay_ms\":" << settings_.model_queue_delay_ms
               << ",\"model_queue_delay_mode\":" << quoted(settings_.model_queue_delay_mode)
               << ",\"executor_contention_enabled\":" << json_bool(executor_contention_enabled_)
               << ",\"executor_contention_period_ms\":" << executor_contention_period_ms_
               << ",\"executor_contention_load_ms\":" << executor_contention_load_ms_
               << ",\"llm_timeout_s\":" << llm_timeout_s_;
  publish_event(
    *frame, "planner_process_start", request, nullptr, nullptr,
    backend_selection_.active, false, "", 0, 0, "observed", "", start_fields.str());

  apply_controlled_delay(settings_.model_queue_delay_ms, settings_.model_queue_delay_mode);
  const auto queue_reason = robotraceopt::planner::ModelAdmission::output_allowed(
    request, steady_now_ns());
  if (!queue_reason.empty()) {
    reject_without_model(
      *frame, request, "planner_queue_deadline_exceeded", queue_reason, started_ns);
    return;
  }

  const auto result = plan(request);
  const auto finished_ns = steady_now_ns();
  const auto output_reason = robotraceopt::planner::ModelAdmission::output_allowed(
    request, finished_ns);
  if (!output_reason.empty()) {
    publish_event(
      *frame, "planner_output_stale", request, &result, nullptr, "abstain", true,
      output_reason, finished_ns, finished_ns - started_ns, "rejected", output_reason);
    publish_abstention(
      *frame, request, result, output_reason, started_ns, finished_ns);
    return;
  }

  if (!result.succeeded()) {
    const auto reason = result.error_code.empty() ? "backend_failure" : result.error_code;
    publish_event(
      *frame, "planner_backend_failure", request, &result, nullptr, "abstain", true,
      reason, finished_ns, finished_ns - started_ns, "error", reason);
    if (model_admission_->note_backend_failure(finished_ns)) {
      std::ostringstream storm_fields;
      storm_fields << ",\"model_failure_count_in_window\":"
                   << model_admission_->failure_count_in_window()
                   << ",\"model_failure_storm_count\":" << model_failure_storm_count_;
      publish_event(
        *frame, "planner_fallback_storm", request, &result, nullptr, "abstain", true,
        reason, finished_ns, finished_ns - started_ns, "rejected", "planner_fallback_storm",
        storm_fields.str());
    }
    publish_abstention(*frame, request, result, reason, started_ns, finished_ns);
    return;
  }

  const auto & decision = *result.decision;
  const auto decision_reason = robotraceopt::planner::validate_decision(decision);
  if (!decision_reason.empty()) {
    publish_event(
      *frame, "planner_decision_rejected", request, &result, &decision, "abstain", true,
      decision_reason, finished_ns, finished_ns - started_ns, "rejected", decision_reason);
    publish_abstention(
      *frame, request, result, decision_reason, started_ns, finished_ns);
    return;
  }

  publish_event(
    *frame, "planner_process_end", request, &result, &decision, result.backend, false, "",
    finished_ns, finished_ns - started_ns);
  const auto command = make_command(*frame, decision);
  command_publisher_->publish(command);
  publish_event(
    *frame, "planner_publish", request, &result, &decision, result.backend, false, "",
    command.header.timestamp_ns);
}

void VlmPlannerNode::run_executor_contention() const
{
  apply_controlled_delay(executor_contention_load_ms_, "busy_compute");
}

VlmPlannerNode::ModelRequest VlmPlannerNode::make_model_request(
  const CameraFrame & frame, const std::int64_t now_ns) const
{
  ModelRequest request;
  request.request_id = make_request_id(session_id_, frame);
  request.session_id = session_id_;
  request.trace_id = frame.header.trace_id;
  request.oracle_id = frame.header.oracle_id;
  request.sequence_id = frame.header.sequence_id;
  request.observation_timestamp_ns = frame.header.timestamp_ns;
  request.created_timestamp_ns = now_ns;
  request.deadline_ns = saturating_deadline(frame.header.timestamp_ns, observation_ttl_ms_);
  request.input_fingerprint = frame_fingerprint(frame);
  return request;
}

VlmPlannerNode::ModelResult VlmPlannerNode::plan(const ModelRequest & request) const
{
  if (!backend_selection_.motion_enabled()) {
    return ModelResult{
      "abstain", std::nullopt, 0,
      std::string{robotraceopt::planner::planner_error_code_name(
          robotraceopt::planner::PlannerErrorCode::kConfiguration)},
      {}, {}, false};
  }

  const auto model_started_ns = steady_now_ns();
  apply_controlled_delay(settings_.planner_delay_ms, settings_.planner_delay_mode);
  auto result = mock_client_.plan_with_request(request);
  result.backend = "mock";
  result.latency_ns = std::max<std::int64_t>(steady_now_ns() - model_started_ns, 0);
  return result;
}

VlmPlannerNode::PlannerCommand VlmPlannerNode::make_command(
  const CameraFrame & frame, const PlannerDecision & decision) const
{
  PlannerCommand command;
  command.header.trace_id = frame.header.trace_id;
  command.header.oracle_id = frame.header.oracle_id;
  command.header.sequence_id = frame.header.sequence_id;
  command.header.source_node = this->get_name();
  command.header.stage = "planner_publish";
  command.header.timestamp_ns = steady_now_ns();
  command.action = decision.action;
  command.target = decision.target;
  command.speed = static_cast<float>(decision.speed);
  command.confidence = static_cast<float>(decision.confidence);
  command.reason = decision.reason;
  return command;
}

void VlmPlannerNode::reject_without_model(
  const CameraFrame & frame, const ModelRequest & request,
  const std::string & stage, const std::string & reason_code,
  const std::int64_t started_ns)
{
  const ModelResult result{
    backend_selection_.active, std::nullopt, 0, reason_code, {}, {}, false};
  const auto finished_ns = steady_now_ns();
  publish_event(
    frame, stage, request, &result, nullptr, "abstain", true, reason_code,
    finished_ns, finished_ns - started_ns, "rejected", reason_code);
  publish_abstention(frame, request, result, reason_code, started_ns, finished_ns);
}

void VlmPlannerNode::publish_abstention(
  const CameraFrame & frame, const ModelRequest & request,
  const ModelResult & result, const std::string & reason_code,
  const std::int64_t started_ns, const std::int64_t finished_ns)
{
  publish_event(
    frame, "planner_process_end", request, &result, nullptr, "abstain", true,
    reason_code, finished_ns, finished_ns - started_ns, "rejected", reason_code);
  publish_event(
    frame, "planner_command_abstained", request, &result, nullptr, "abstain", true,
    reason_code, finished_ns, finished_ns - started_ns, "rejected",
    "planner_fail_closed_abstain");
}

void VlmPlannerNode::publish_event(
  const CameraFrame & frame, const std::string & stage,
  const ModelRequest & request, const ModelResult * result,
  const PlannerDecision * decision, const std::string & effective_backend,
  const bool used_fallback, const std::string & fallback_reason,
  std::int64_t timestamp_ns, const std::int64_t duration_ns,
  const std::string & status, const std::string & reason_code,
  const std::string & additional_fields) const
{
  if (!runtime_events_enabled_) {
    return;
  }
  if (timestamp_ns == 0) {
    timestamp_ns = steady_now_ns();
  }
  RuntimeEvent event;
  event.header.trace_id = frame.header.trace_id;
  event.header.oracle_id = frame.header.oracle_id;
  event.header.sequence_id = frame.header.sequence_id;
  event.header.source_node = this->get_name();
  event.header.stage = stage;
  event.header.timestamp_ns = timestamp_ns;
  event.event_name = stage;
  event.event_type = "planner";
  ai_robot_runtime_interfaces::populate_runtime_identity(event, "monotonic", status, reason_code);
  event.duration_ns = std::max<std::int64_t>(duration_ns, 0);
  event.extra_json = make_event_extra(
    frame, request, result, decision, effective_backend, used_fallback,
    fallback_reason, additional_fields);
  event_publisher_->publish(event);
}

std::string VlmPlannerNode::make_event_extra(
  const CameraFrame & frame, const ModelRequest & request,
  const ModelResult * result, const PlannerDecision * decision,
  const std::string & effective_backend, const bool used_fallback,
  const std::string & fallback_reason, const std::string & additional_fields) const
{
  std::ostringstream stream;
  stream << "{\"frame_id\":" << frame.frame_id
         << ",\"planner_backend\":" << quoted(backend_selection_.requested)
         << ",\"effective_backend\":" << quoted(effective_backend)
         << ",\"used_fallback\":" << json_bool(used_fallback)
         << ",\"legacy_mock_fallback_requested\":" << json_bool(fallback_to_mock_)
         << ",\"motion_mock_backend_explicit\":"
         << json_bool(backend_selection_.requested == "mock")
         << ",\"observation_ttl_ms\":" << observation_ttl_ms_
         << ",\"llm_provider\":" << quoted(llm_provider_)
         << ",\"llm_api_style\":" << quoted(llm_api_style_)
         << ",\"llm_vision_mode\":" << quoted(llm_vision_mode_)
         << ",\"action\":" << (decision ? quoted(decision->action) : "null")
         << ",\"target\":" << (decision ? quoted(decision->target) : "null")
         << ",\"speed\":";
  if (decision) {
    stream << decision->speed;
  } else {
    stream << "null";
  }
  stream << ",\"confidence\":";
  if (decision) {
    stream << decision->confidence;
  } else {
    stream << "null";
  }
  stream << ",\"reason\":" << (decision ? quoted(decision->reason) : "null")
         << ",\"executor_threads\":" << settings_.executor_threads
         << ",\"frame_qos_depth\":" << settings_.frame_qos_depth
         << ",\"frame_qos_reliability\":" << quoted(settings_.frame_qos_reliability)
         << ",\"request_id\":" << quoted(request.request_id)
         << ",\"session_id\":" << quoted(request.session_id)
         << ",\"trace_id\":" << quoted(request.trace_id)
         << ",\"oracle_id\":" << quoted(request.oracle_id)
         << ",\"sequence_id\":" << request.sequence_id
         << ",\"observation_timestamp_ns\":" << request.observation_timestamp_ns
         << ",\"created_timestamp_ns\":" << request.created_timestamp_ns
         << ",\"deadline_ns\":" << request.deadline_ns
         << ",\"input_fingerprint\":" << quoted(request.input_fingerprint)
         << ",\"prompt_version\":" << quoted(request.prompt_version)
         << ",\"output_schema_version\":" << quoted(request.output_schema_version);
  if (result) {
    stream << ",\"model_backend\":" << quoted(result->backend)
           << ",\"model_latency_ns\":" << result->bounded_latency_ns()
           << ",\"model_error_code\":" << quoted(result->error_code)
           << ",\"model_response_fingerprint\":" << quoted(result->response_fingerprint)
           << ",\"model_replayed\":" << json_bool(result->replayed);
    if (!result->provider_response_id.empty()) {
      stream << ",\"provider_response_id\":" << quoted(result->provider_response_id);
    }
  }
  if (!llm_model_.empty()) {
    stream << ",\"llm_model\":" << quoted(llm_model_);
  }
  if (!fallback_reason.empty()) {
    stream << ",\"fallback_reason\":" << quoted(fallback_reason);
  }
  stream << additional_fields << "}";
  return stream.str();
}

std::int64_t VlmPlannerNode::steady_now_ns()
{
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
    std::chrono::steady_clock::now().time_since_epoch()).count();
}

std::string VlmPlannerNode::make_session_id()
{
  std::random_device random;
  std::ostringstream stream;
  stream << ai_robot_runtime_interfaces::current_host_id() << "-"
         << std::hex << steady_now_ns() << random();
  return stream.str();
}

std::string VlmPlannerNode::make_request_id(
  const std::string & session_id, const CameraFrame & frame)
{
  auto hash = fnv_string(kFnvOffset, session_id);
  hash = fnv_string(hash, frame.header.trace_id);
  hash = fnv_string(hash, frame.header.oracle_id);
  hash = fnv_value(hash, frame.header.sequence_id);
  return hex_digest(hash);
}

std::string VlmPlannerNode::frame_fingerprint(const CameraFrame & frame)
{
  auto hash = fnv_string(kFnvOffset, frame.encoding);
  hash = fnv_value(hash, frame.frame_id);
  hash = fnv_value(hash, frame.width);
  hash = fnv_value(hash, frame.height);
  if (!frame.payload.empty()) {
    hash = fnv_update(hash, frame.payload.data(), frame.payload.size());
  }
  return hex_digest(hash);
}

}  // namespace vlm_planner_cpp_pkg
