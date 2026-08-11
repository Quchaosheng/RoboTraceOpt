#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

namespace robotraceopt::planner {

inline constexpr std::string_view kPromptVersion = "planner-prompt/v1";
inline constexpr std::string_view kOutputSchemaVersion = "planner-decision/v1";
inline constexpr std::string_view kRecordingSchemaVersion =
    "planner-decision-record/v1";

enum class PlannerErrorCode {
  kBackendFailure,
  kConfiguration,
  kDeadlineExceeded,
  kHttpFailure,
  kInvalidResponse,
  kNetworkFailure,
  kReplayMiss,
  kTimeout,
};

std::string_view planner_error_code_name(PlannerErrorCode code) noexcept;

struct PlannerDecision {
  std::string action;
  std::string target;
  double speed{0.0};
  double confidence{0.0};
  std::string reason;
};

bool operator==(const PlannerDecision& left, const PlannerDecision& right) noexcept;
bool operator!=(const PlannerDecision& left, const PlannerDecision& right) noexcept;

struct ModelRequest {
  std::string request_id;
  std::string session_id;
  std::string trace_id;
  std::string oracle_id;
  std::uint64_t sequence_id{0};
  std::int64_t observation_timestamp_ns{0};
  std::int64_t created_timestamp_ns{0};
  std::int64_t deadline_ns{0};
  std::string input_fingerprint;
  std::string prompt_version{std::string{kPromptVersion}};
  std::string output_schema_version{std::string{kOutputSchemaVersion}};

  [[nodiscard]] bool expired(std::int64_t now_ns) const noexcept;
};

struct ModelResult {
  std::string backend;
  std::optional<PlannerDecision> decision;
  std::int64_t latency_ns{0};
  std::string error_code;
  std::string provider_response_id;
  std::string response_fingerprint;
  bool replayed{false};

  [[nodiscard]] bool succeeded() const noexcept;
  [[nodiscard]] std::int64_t bounded_latency_ns() const noexcept;
};

// Returns an empty string for an admissible decision, otherwise the exact
// public reason code consumed by RuntimeEvent and downstream campaign checks.
[[nodiscard]] std::string validate_decision(const PlannerDecision& decision);

// Dependency-free equivalent of the Python exception classifier. Adapters
// provide a stable exception type name and a sanitized message.
[[nodiscard]] PlannerErrorCode classify_backend_error(
    std::string_view type_name, std::string_view message);

}  // namespace robotraceopt::planner
