#pragma once

#include "robotraceopt/optimizer/runtime_objective.hpp"
#include "robotraceopt/optimizer/types.hpp"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace robotraceopt::optimizer {

struct BootstrapOptions {
    double confidence_level{0.95};
    std::size_t resamples{10000};
    std::uint64_t seed{0};
};

struct BootstrapInterval {
    std::optional<double> estimate;
    std::optional<double> lower;
    std::optional<double> upper;
};

BootstrapInterval percentile_bootstrap_interval(
    const std::vector<double>& values,
    const BootstrapOptions& options = {});

enum class ValidationDecision { Accept, Reject };

struct CandidateValidationOptions {
    double minimum_improvement_ratio{0.0};
    double minimum_complete_trace_rate_delta{0.0};
    bool formal{false};
};

struct CandidateValidationResult {
    static constexpr const char* schema_version = "candidate-validation/v1";

    ValidationDecision decision{ValidationDecision::Reject};
    std::string reason_code;
    bool rollback_required{true};
    double improvement_ratio{};
    double complete_trace_rate_delta{};
    bool formal_validation{};
};

CandidateValidationResult validate_candidate_objectives(
    const RuntimeObjective& baseline,
    const RuntimeObjective& candidate,
    const CandidateValidationOptions& options = {});

enum class ConfigurationRole { Baseline, Candidate };
enum class TrialStatus { Succeeded, Failed };
enum class PairStatus { Succeeded, Failed, Missing };

struct RepeatedConfiguration {
    int config_index{};
    std::string config_id;
    ConfigurationRole role{ConfigurationRole::Candidate};
    CandidateConfiguration candidate_config;
};

struct RepeatedSchedule {
    std::string schema_version{"optimization-repeated-schedule/v1"};
    std::size_t repetitions{};
    std::vector<RepeatedConfiguration> configurations;
};

struct RepeatedTrialRecord {
    std::size_t block_index{};
    std::string config_id;
    ConfigurationRole role{ConfigurationRole::Candidate};
    CandidateConfiguration candidate_config;
    TrialStatus status{TrialStatus::Failed};
    std::optional<double> objective_value_ns;
    std::optional<double> complete_trace_rate;
};

struct PairResult {
    std::size_t block_index{};
    PairStatus status{PairStatus::Missing};
    std::optional<double> improvement_ratio;
    std::optional<double> complete_trace_rate_delta;
};

struct RepeatedValidationOptions {
    double minimum_improvement_ratio{};
    double minimum_complete_trace_rate_delta{};
    BootstrapOptions bootstrap;
};

struct RepeatedCandidateValidation {
    static constexpr const char* schema_version =
        "repeated-candidate-validation/v1";

    int config_index{};
    std::string config_id;
    CandidateConfiguration candidate_config;
    ValidationDecision decision{ValidationDecision::Reject};
    std::string reason_code;
    bool rollback_required{true};
    std::size_t planned_pair_count{};
    std::size_t successful_pair_count{};
    std::size_t failed_pair_count{};
    std::size_t missing_pair_count{};
    double confidence_level{};
    std::size_t bootstrap_resamples{};
    double minimum_improvement_ratio{};
    double minimum_complete_trace_rate_delta{};
    BootstrapInterval improvement_ratio;
    BootstrapInterval complete_trace_rate_delta;
    std::optional<double> median_candidate_objective_ns;
    std::vector<PairResult> pairs;
};

std::vector<RepeatedCandidateValidation> evaluate_repeated_candidates(
    const RepeatedSchedule& schedule,
    const std::vector<RepeatedTrialRecord>& records,
    const RepeatedValidationOptions& options);

}  // namespace robotraceopt::optimizer
