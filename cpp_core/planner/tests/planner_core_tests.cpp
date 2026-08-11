#include "robotraceopt/planner/clients.hpp"
#include "robotraceopt/planner/model_admission.hpp"
#include "robotraceopt/planner/model_contract.hpp"

#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using robotraceopt::planner::DecisionRecord;
using robotraceopt::planner::MockPlannerClient;
using robotraceopt::planner::ModelAdmission;
using robotraceopt::planner::ModelRequest;
using robotraceopt::planner::ModelResult;
using robotraceopt::planner::PlannerDecision;
using robotraceopt::planner::PlannerErrorCode;
using robotraceopt::planner::ReplayPlannerClient;
using robotraceopt::planner::classify_backend_error;
using robotraceopt::planner::kOutputSchemaVersion;
using robotraceopt::planner::kPromptVersion;
using robotraceopt::planner::kRecordingSchemaVersion;
using robotraceopt::planner::planner_error_code_name;
using robotraceopt::planner::replay_key;
using robotraceopt::planner::validate_decision;

int checks = 0;

void require(bool condition, const std::string& message) {
  ++checks;
  if (!condition) {
    throw std::runtime_error(message);
  }
}

template <typename Function>
void require_invalid_argument(Function&& function, const std::string& message) {
  bool raised = false;
  try {
    std::forward<Function>(function)();
  } catch (const std::invalid_argument&) {
    raised = true;
  }
  require(raised, message);
}

ModelRequest request(std::string request_id = "request-1") {
  return ModelRequest{
      std::move(request_id),
      "session-1",
      "trace-7",
      "oracle-7",
      11,
      1'000'000'000,
      1'010'000'000,
      1'250'000'000,
      "frame-fingerprint",
      std::string{kPromptVersion},
      std::string{kOutputSchemaVersion},
  };
}

void test_public_contract_types() {
  require(planner_error_code_name(PlannerErrorCode::kBackendFailure) ==
              "backend_failure",
          "backend failure code changed");
  require(planner_error_code_name(PlannerErrorCode::kConfiguration) ==
              "configuration_error",
          "configuration code changed");
  require(planner_error_code_name(PlannerErrorCode::kDeadlineExceeded) ==
              "deadline_exceeded",
          "deadline code changed");
  require(planner_error_code_name(PlannerErrorCode::kHttpFailure) ==
              "http_failure",
          "HTTP code changed");
  require(planner_error_code_name(PlannerErrorCode::kInvalidResponse) ==
              "invalid_response",
          "response code changed");
  require(planner_error_code_name(PlannerErrorCode::kNetworkFailure) ==
              "network_failure",
          "network code changed");
  require(planner_error_code_name(PlannerErrorCode::kReplayMiss) ==
              "replay_miss",
          "replay code changed");
  require(planner_error_code_name(PlannerErrorCode::kTimeout) == "timeout",
          "timeout code changed");

  auto model_request = request();
  require(!model_request.expired(1'250'000'000),
          "deadline must remain valid at equality");
  require(model_request.expired(1'250'000'001),
          "deadline must expire strictly after equality");
  model_request.deadline_ns = 0;
  require(!model_request.expired(std::numeric_limits<std::int64_t>::max()),
          "zero deadline must remain unbounded");

  ModelResult empty{"mock", std::nullopt, -4, {}, {}, {}, false};
  require(!empty.succeeded(), "result without a decision must fail");
  require(empty.bounded_latency_ns() == 0, "negative latency must clamp to zero");
  empty.decision = PlannerDecision{"stop", "hold", 0.0, 1.0, "safe"};
  require(empty.succeeded(), "valid decision without error must succeed");
  empty.error_code = "backend_failure";
  require(!empty.succeeded(), "decision with error must fail closed");
}

void test_decision_validation() {
  const PlannerDecision valid{"move_forward", "front", 0.2, 0.9, "clear"};
  require(validate_decision(valid).empty(), "valid decision was rejected");
  require(validate_decision({"dance", "front", 0.2, 0.9, "bad"}) ==
              "planner_decision_action_not_allowed",
          "unknown action reason changed");
  require(validate_decision({"move_forward", "front",
                             std::numeric_limits<double>::quiet_NaN(), 0.9,
                             "bad"}) == "planner_decision_speed_not_finite",
          "NaN speed must be rejected");
  require(validate_decision({"move_forward", "front", 1.01, 0.9, "bad"}) ==
              "planner_decision_speed_out_of_range",
          "out-of-range speed must be rejected");
  require(validate_decision({"move_forward", "front", 0.2,
                             std::numeric_limits<double>::infinity(), "bad"}) ==
              "planner_decision_confidence_not_finite",
          "infinite confidence must be rejected");
  require(validate_decision({"move_forward", "front", 0.2, -0.01, "bad"}) ==
              "planner_decision_confidence_out_of_range",
          "out-of-range confidence must be rejected");
  require(validate_decision({"stop", "hold", 0.1, 1.0, "bad"}) ==
              "planner_decision_stop_speed_nonzero",
          "moving stop command must be rejected");
  require(validate_decision({"stop", "hold", 0.0, 1.0, "safe"}).empty(),
          "stationary stop command must be valid");
}

void test_error_classification() {
  require(classify_backend_error("TimeoutError", "provider timed out") ==
              PlannerErrorCode::kTimeout,
          "timeout classification changed");
  require(classify_backend_error("JsonError", "bad body") ==
              PlannerErrorCode::kInvalidResponse,
          "JSON classification changed");
  require(classify_backend_error("RuntimeError", "HTTP status 401") ==
              PlannerErrorCode::kHttpFailure,
          "HTTP classification changed");
  require(classify_backend_error("SocketError", "connect failed") ==
              PlannerErrorCode::kNetworkFailure,
          "network classification changed");
  require(classify_backend_error("RuntimeError", "unsupported provider config") ==
              PlannerErrorCode::kConfiguration,
          "configuration classification changed");
  require(classify_backend_error("RuntimeError", "opaque failure") ==
              PlannerErrorCode::kBackendFailure,
          "fallback classification changed");
}

void test_admission_contract() {
  require_invalid_argument([] { ModelAdmission admission(0, 50, 3); },
                           "zero dedup window must fail");
  require_invalid_argument([] { ModelAdmission admission(100, 0, 3); },
                           "zero failure window must fail");
  require_invalid_argument([] { ModelAdmission admission(100, 50, 0); },
                           "zero failure threshold must fail");
  require_invalid_argument([] { ModelAdmission admission(100, 50, 3, -1); },
                           "negative future skew must fail");

  ModelAdmission admission(100, 50, 3);
  auto model_request = request();
  auto missing_identity = model_request;
  missing_identity.trace_id.clear();
  require(admission.admit(missing_identity, 1'010'000'000) ==
              "planner_request_identity_missing",
          "missing identity reason changed");
  auto missing_timestamp = model_request;
  missing_timestamp.observation_timestamp_ns = 0;
  require(admission.admit(missing_timestamp, 1'010'000'000) ==
              "planner_observation_timestamp_missing",
          "missing timestamp reason changed");
  auto future = model_request;
  future.observation_timestamp_ns = 1'110'000'001;
  require(admission.admit(future, 1'010'000'000) ==
              "planner_observation_timestamp_future",
          "future-skew reason changed");
  future.observation_timestamp_ns = 1'110'000'000;
  future.deadline_ns = 1'500'000'000;
  future.request_id = "future-boundary";
  require(admission.admit(future, 1'010'000'000).empty(),
          "future-skew equality must be admitted");

  require(admission.admit(model_request, 1'010'000'000).empty(),
          "first request must be admitted");
  require(admission.admit(model_request, 1'011'000'000) ==
              "planner_duplicate_request",
          "duplicate request must be rejected");
  require(ModelAdmission::output_allowed(model_request, 1'250'000'000).empty(),
          "output at deadline must remain valid");
  require(ModelAdmission::output_allowed(model_request, 1'250'000'001) ==
              "planner_output_expired",
          "stale output reason changed");

  auto stale = request("stale");
  require(admission.admit(stale, 1'250'000'001) ==
              "planner_observation_expired",
          "stale observation reason changed");

  auto no_deadline = request("dedup-boundary");
  no_deadline.deadline_ns = 0;
  require(admission.admit(no_deadline, 2'000'000'000).empty(),
          "unbounded request must be admitted");
  require(admission.admit(no_deadline, 2'099'999'999) ==
              "planner_duplicate_request",
          "request must remain duplicate inside window");
  require(admission.admit(no_deadline, 2'100'000'000).empty(),
          "request must be admissible at dedup expiry equality");

  require(!admission.note_backend_failure(3'000'000'000),
          "first failure must not trigger storm");
  require(!admission.note_backend_failure(3'010'000'000),
          "second failure must not trigger storm");
  require(admission.note_backend_failure(3'020'000'000),
          "third failure must trigger storm");
  require(admission.failure_count_in_window() == 3,
          "failure count must expose current window");
  require(!admission.note_backend_failure(3'070'000'000),
          "cutoff equality must purge old failures");
  require(admission.failure_count_in_window() == 1,
          "purged failure count changed");
}

void test_mock_and_replay_clients() {
  const auto model_request = request();
  const auto mock = MockPlannerClient{}.plan_with_request(model_request);
  require(mock.succeeded(), "mock client must succeed deterministically");
  require(mock.backend == "mock", "mock backend name changed");
  require(mock.decision ==
              PlannerDecision{"move_forward", "front", 0.2, 0.9,
                              "mock planner output"},
          "mock decision changed");
  require(validate_decision(*mock.decision).empty(),
          "mock decision must satisfy publication guard");

  auto recorded_result = mock;
  recorded_result.backend = "llm";
  recorded_result.latency_ns = 42;
  recorded_result.provider_response_id = "provider-secret-id";
  recorded_result.response_fingerprint = "response-fingerprint";
  const DecisionRecord record{std::string{kRecordingSchemaVersion},
                              model_request, recorded_result};
  const ReplayPlannerClient replay({record});
  const auto replayed = replay.plan_with_request(model_request);
  require(replay.record_count() == 1, "replay record count changed");
  require(replayed.succeeded(), "unique replay match must succeed");
  require(replayed.backend == "replay", "replay backend name changed");
  require(replayed.replayed, "replay marker must be true");
  require(replayed.decision == recorded_result.decision,
          "replay decision must remain normalized");
  require(replayed.response_fingerprint == "response-fingerprint",
          "replay fingerprint must be retained");
  require(replayed.provider_response_id.empty(),
          "provider response id must not escape replay");

  auto unmatched = model_request;
  unmatched.input_fingerprint = "different-frame";
  const auto miss = replay.plan_with_request(unmatched);
  require(!miss.succeeded(), "missing replay match must fail closed");
  require(miss.error_code == "replay_miss", "replay miss reason changed");
  require(miss.replayed, "replay miss must retain replay marker");

  const ReplayPlannerClient ambiguous({record, record});
  const auto duplicate = ambiguous.plan_with_request(model_request);
  require(!duplicate.succeeded(), "ambiguous replay must fail closed");
  require(duplicate.error_code == "replay_miss",
          "ambiguous replay reason changed");

  auto wrong_schema = record;
  wrong_schema.schema_version = "planner-decision-record/v0";
  require_invalid_argument(
      [&wrong_schema] { ReplayPlannerClient unsupported({wrong_schema}); },
      "unsupported record schema must fail during replay loading");

  auto changed_prompt = model_request;
  changed_prompt.prompt_version = "planner-prompt/v2";
  require(replay_key(changed_prompt) != replay_key(model_request),
          "prompt version must participate in replay key");
}

}  // namespace

int main() {
  try {
    test_public_contract_types();
    test_decision_validation();
    test_error_classification();
    test_admission_contract();
    test_mock_and_replay_clients();
  } catch (const std::exception& error) {
    std::cerr << "planner core test failed after " << checks
              << " checks: " << error.what() << '\n';
    return 1;
  }
  std::cout << "planner core tests passed: " << checks << " checks\n";
  return 0;
}
