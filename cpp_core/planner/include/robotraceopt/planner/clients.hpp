#pragma once

#include <cstddef>
#include <string>
#include <tuple>
#include <vector>

#include "robotraceopt/planner/model_contract.hpp"

namespace robotraceopt::planner {

class PlannerClient {
 public:
  virtual ~PlannerClient() = default;
  [[nodiscard]] virtual ModelResult plan_with_request(
      const ModelRequest& request) const = 0;
};

class MockPlannerClient final : public PlannerClient {
 public:
  [[nodiscard]] ModelResult plan_with_request(
      const ModelRequest& request) const override;
};

struct DecisionRecord {
  std::string schema_version{std::string{kRecordingSchemaVersion}};
  ModelRequest request;
  ModelResult result;
};

using ReplayKey = std::tuple<std::string, std::string, std::string>;

[[nodiscard]] ReplayKey replay_key(const ModelRequest& request);
[[nodiscard]] std::vector<const DecisionRecord*> records_for_request(
    const std::vector<DecisionRecord>& records, const ModelRequest& request);

class ReplayPlannerClient final : public PlannerClient {
 public:
  explicit ReplayPlannerClient(std::vector<DecisionRecord> records);

  [[nodiscard]] ModelResult plan_with_request(
      const ModelRequest& request) const override;
  [[nodiscard]] std::size_t record_count() const noexcept;

 private:
  std::vector<DecisionRecord> records_;
};

}  // namespace robotraceopt::planner
