#include "robotraceopt/planner/model_contract.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <iterator>
#include <string>
#include <unordered_set>

namespace robotraceopt::planner {
namespace {

std::string lower_copy(std::string_view value) {
  std::string lowered;
  lowered.reserve(value.size());
  std::transform(value.begin(), value.end(), std::back_inserter(lowered),
                 [](unsigned char character) {
                   return static_cast<char>(std::tolower(character));
                 });
  return lowered;
}

bool contains(const std::string& value, std::string_view needle) {
  return value.find(needle) != std::string::npos;
}

}  // namespace

std::string_view planner_error_code_name(PlannerErrorCode code) noexcept {
  switch (code) {
    case PlannerErrorCode::kBackendFailure:
      return "backend_failure";
    case PlannerErrorCode::kConfiguration:
      return "configuration_error";
    case PlannerErrorCode::kDeadlineExceeded:
      return "deadline_exceeded";
    case PlannerErrorCode::kHttpFailure:
      return "http_failure";
    case PlannerErrorCode::kInvalidResponse:
      return "invalid_response";
    case PlannerErrorCode::kNetworkFailure:
      return "network_failure";
    case PlannerErrorCode::kReplayMiss:
      return "replay_miss";
    case PlannerErrorCode::kTimeout:
      return "timeout";
  }
  return "backend_failure";
}

bool operator==(const PlannerDecision& left,
                const PlannerDecision& right) noexcept {
  return left.action == right.action && left.target == right.target &&
         left.speed == right.speed && left.confidence == right.confidence &&
         left.reason == right.reason;
}

bool operator!=(const PlannerDecision& left,
                const PlannerDecision& right) noexcept {
  return !(left == right);
}

bool ModelRequest::expired(std::int64_t now_ns) const noexcept {
  return deadline_ns > 0 && now_ns > deadline_ns;
}

bool ModelResult::succeeded() const noexcept {
  return decision.has_value() && error_code.empty();
}

std::int64_t ModelResult::bounded_latency_ns() const noexcept {
  return std::max<std::int64_t>(latency_ns, 0);
}

std::string validate_decision(const PlannerDecision& decision) {
  static const std::unordered_set<std::string> kAllowedActions{
      "move_forward", "turn_left", "turn_right", "stop", "inspect"};

  if (kAllowedActions.find(decision.action) == kAllowedActions.end()) {
    return "planner_decision_action_not_allowed";
  }
  if (!std::isfinite(decision.speed)) {
    return "planner_decision_speed_not_finite";
  }
  if (decision.speed < 0.0 || decision.speed > 1.0) {
    return "planner_decision_speed_out_of_range";
  }
  if (!std::isfinite(decision.confidence)) {
    return "planner_decision_confidence_not_finite";
  }
  if (decision.confidence < 0.0 || decision.confidence > 1.0) {
    return "planner_decision_confidence_out_of_range";
  }
  if (decision.action == "stop" && decision.speed != 0.0) {
    return "planner_decision_stop_speed_nonzero";
  }
  return {};
}

PlannerErrorCode classify_backend_error(std::string_view type_name,
                                        std::string_view message) {
  const auto name = lower_copy(type_name);
  const auto text = lower_copy(message);
  if (contains(name, "timeout") || contains(text, "timed out") ||
      contains(text, "timeout")) {
    return PlannerErrorCode::kTimeout;
  }
  if (contains(name, "json") || contains(text, "json") ||
      contains(text, "response")) {
    return PlannerErrorCode::kInvalidResponse;
  }
  if (contains(name, "http") || contains(text, "http status")) {
    return PlannerErrorCode::kHttpFailure;
  }
  if (contains(name, "url") || contains(name, "socket") ||
      contains(name, "connection") || contains(text, "network")) {
    return PlannerErrorCode::kNetworkFailure;
  }
  if (contains(text, "config") || contains(text, "missing llm") ||
      contains(text, "unsupported")) {
    return PlannerErrorCode::kConfiguration;
  }
  return PlannerErrorCode::kBackendFailure;
}

}  // namespace robotraceopt::planner
