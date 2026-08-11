#include "robotraceopt/planner/clients.hpp"

#include <stdexcept>
#include <utility>

namespace robotraceopt::planner {

ModelResult MockPlannerClient::plan_with_request(
    const ModelRequest& request) const {
  static_cast<void>(request);
  return ModelResult{
      "mock",
      PlannerDecision{"move_forward", "front", 0.2, 0.9,
                      "mock planner output"},
      0,
      {},
      {},
      {},
      false,
  };
}

ReplayKey replay_key(const ModelRequest& request) {
  return {request.input_fingerprint, request.prompt_version,
          request.output_schema_version};
}

std::vector<const DecisionRecord*> records_for_request(
    const std::vector<DecisionRecord>& records, const ModelRequest& request) {
  const auto key = replay_key(request);
  std::vector<const DecisionRecord*> matches;
  for (const auto& record : records) {
    if (record.schema_version == kRecordingSchemaVersion &&
        replay_key(record.request) == key) {
      matches.push_back(&record);
    }
  }
  return matches;
}

ReplayPlannerClient::ReplayPlannerClient(std::vector<DecisionRecord> records)
    : records_(std::move(records)) {
  for (const auto& record : records_) {
    if (record.schema_version != kRecordingSchemaVersion) {
      throw std::invalid_argument("unsupported planner recording schema");
    }
  }
}

ModelResult ReplayPlannerClient::plan_with_request(
    const ModelRequest& request) const {
  const auto matches = records_for_request(records_, request);
  if (matches.size() != 1) {
    return ModelResult{
        "replay",
        std::nullopt,
        0,
        std::string{planner_error_code_name(PlannerErrorCode::kReplayMiss)},
        {},
        {},
        true,
    };
  }

  auto result = matches.front()->result;
  result.backend = "replay";
  result.latency_ns = result.bounded_latency_ns();
  result.provider_response_id.clear();
  result.replayed = true;
  return result;
}

std::size_t ReplayPlannerClient::record_count() const noexcept {
  return records_.size();
}

}  // namespace robotraceopt::planner
