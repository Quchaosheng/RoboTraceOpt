#include <iostream>
#include <string>

#include "robotraceopt/planner/model_contract.hpp"

int main() {
  using robotraceopt::planner::PlannerDecision;
  using robotraceopt::planner::validate_decision;

  const PlannerDecision valid{"stop", "hold", 0.0, 1.0, "safe"};
  const std::string valid_result = validate_decision(valid);
  if (!valid_result.empty()) {
    std::cerr << "valid planner decision was rejected: " << valid_result << '\n';
    return 1;
  }

  const PlannerDecision invalid{"move_forward", "front", 1.1, 0.9,
                                "too fast"};
  const std::string invalid_result = validate_decision(invalid);
  if (invalid_result != "planner_decision_speed_out_of_range") {
    std::cerr << "unexpected validation result: " << invalid_result << '\n';
    return 1;
  }

  return 0;
}
