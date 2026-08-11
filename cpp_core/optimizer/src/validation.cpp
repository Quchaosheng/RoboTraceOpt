#include "robotraceopt/optimizer/validation.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <stdexcept>
#include <utility>

namespace robotraceopt::optimizer {
namespace {

class StableRandom {
public:
    explicit StableRandom(std::uint64_t seed) : state_(seed) {}

    std::uint64_t next() noexcept {
        state_ += 0x9E3779B97F4A7C15ULL;
        auto value = state_;
        value = (value ^ (value >> 30U)) * 0xBF58476D1CE4E5B9ULL;
        value = (value ^ (value >> 27U)) * 0x94D049BB133111EBULL;
        return value ^ (value >> 31U);
    }

    std::size_t index(std::size_t bound) {
        if (bound == 0) {
            throw std::logic_error("random index bound must be positive");
        }
        const auto width = static_cast<std::uint64_t>(bound);
        const auto threshold = (std::uint64_t{0} - width) % width;
        std::uint64_t value = 0;
        do {
            value = next();
        } while (value < threshold);
        return static_cast<std::size_t>(value % width);
    }

private:
    std::uint64_t state_;
};

void validate_bootstrap_options(const BootstrapOptions& options) {
    if (!std::isfinite(options.confidence_level) ||
        options.confidence_level <= 0.0 ||
        options.confidence_level >= 1.0) {
        throw std::invalid_argument(
            "confidence level must be between zero and one");
    }
    if (options.resamples < 100) {
        throw std::invalid_argument("bootstrap resamples must be at least 100");
    }
}

double median(std::vector<double> values) {
    if (values.empty()) {
        throw std::logic_error("median requires values");
    }
    std::sort(values.begin(), values.end());
    const auto middle = values.size() / 2;
    if (values.size() % 2 == 1) {
        return values[middle];
    }
    return values[middle - 1] / 2.0 + values[middle] / 2.0;
}

double linear_quantile(
    const std::vector<double>& sorted_values,
    double probability) {
    const double position =
        static_cast<double>(sorted_values.size() - 1) * probability;
    const auto lower = static_cast<std::size_t>(std::floor(position));
    const auto upper = static_cast<std::size_t>(std::ceil(position));
    if (lower == upper) {
        return sorted_values[lower];
    }
    const double weight = position - static_cast<double>(lower);
    return sorted_values[lower] * (1.0 - weight) +
        sorted_values[upper] * weight;
}

void validate_objective(const RuntimeObjective& objective, const char* label) {
    if (!std::isfinite(objective.objective_value_ns) ||
        objective.objective_value_ns <= 0.0) {
        throw std::invalid_argument(
            std::string("invalid ") + label + " objective value");
    }
    if (!std::isfinite(objective.complete_trace_rate) ||
        objective.complete_trace_rate < 0.0 ||
        objective.complete_trace_rate > 1.0) {
        throw std::invalid_argument(
            std::string("invalid ") + label + " complete_trace_rate");
    }
}

double rounded_twelve(double value) {
    constexpr double scale = 1'000'000'000'000.0;
    return std::round(value * scale) / scale;
}

double record_objective(const RepeatedTrialRecord& record) {
    if (!record.objective_value_ns.has_value() ||
        !std::isfinite(*record.objective_value_ns) ||
        *record.objective_value_ns <= 0.0) {
        throw std::invalid_argument("invalid objective");
    }
    return *record.objective_value_ns;
}

double record_rate(const RepeatedTrialRecord& record) {
    if (!record.complete_trace_rate.has_value() ||
        !std::isfinite(*record.complete_trace_rate) ||
        *record.complete_trace_rate < 0.0 ||
        *record.complete_trace_rate > 1.0) {
        throw std::invalid_argument("invalid complete trace rate");
    }
    return *record.complete_trace_rate;
}

}  // namespace

BootstrapInterval percentile_bootstrap_interval(
    const std::vector<double>& values,
    const BootstrapOptions& options) {
    validate_bootstrap_options(options);
    for (const double value : values) {
        if (!std::isfinite(value)) {
            throw std::invalid_argument("invalid bootstrap value");
        }
    }
    if (values.empty()) {
        return {};
    }

    const double estimate = median(values);
    if (values.size() < 2) {
        return {estimate, std::nullopt, std::nullopt};
    }

    StableRandom random(options.seed);
    std::vector<double> samples;
    samples.reserve(options.resamples);
    std::vector<double> draw(values.size());
    for (std::size_t sample = 0; sample < options.resamples; ++sample) {
        for (double& value : draw) {
            value = values[random.index(values.size())];
        }
        samples.push_back(median(draw));
    }
    std::sort(samples.begin(), samples.end());
    const double alpha = (1.0 - options.confidence_level) / 2.0;
    return {
        estimate,
        linear_quantile(samples, alpha),
        linear_quantile(samples, 1.0 - alpha),
    };
}

CandidateValidationResult validate_candidate_objectives(
    const RuntimeObjective& baseline,
    const RuntimeObjective& candidate,
    const CandidateValidationOptions& options) {
    validate_objective(baseline, "baseline");
    validate_objective(candidate, "candidate");
    if (baseline.metric != candidate.metric) {
        throw std::invalid_argument("objective mismatch in metric");
    }
    if (baseline.quantile != candidate.quantile) {
        throw std::invalid_argument("objective mismatch in quantile");
    }
    if (!std::isfinite(options.minimum_improvement_ratio) ||
        options.minimum_improvement_ratio < 0.0 ||
        options.minimum_improvement_ratio > 1.0) {
        throw std::invalid_argument(
            "minimum_improvement_ratio must be between 0 and 1");
    }
    if (!std::isfinite(options.minimum_complete_trace_rate_delta) ||
        options.minimum_complete_trace_rate_delta < -1.0 ||
        options.minimum_complete_trace_rate_delta > 0.0) {
        throw std::invalid_argument(
            "minimum_complete_trace_rate_delta must be between -1 and 0");
    }

    const double improvement =
        (baseline.objective_value_ns - candidate.objective_value_ns) /
        baseline.objective_value_ns;
    const double rate_delta =
        candidate.complete_trace_rate - baseline.complete_trace_rate;
    std::string reason;
    if (options.formal &&
        !(baseline.formal_optimization_allowed &&
          candidate.formal_optimization_allowed)) {
        reason = "formal_evidence_required";
    } else if (rate_delta < options.minimum_complete_trace_rate_delta) {
        reason = "complete_trace_rate_regression";
    } else if (improvement < options.minimum_improvement_ratio) {
        reason = "insufficient_improvement";
    }
    return {
        reason.empty() ? ValidationDecision::Accept : ValidationDecision::Reject,
        reason,
        !reason.empty(),
        rounded_twelve(improvement),
        rounded_twelve(rate_delta),
        options.formal,
    };
}

std::vector<RepeatedCandidateValidation> evaluate_repeated_candidates(
    const RepeatedSchedule& schedule,
    const std::vector<RepeatedTrialRecord>& records,
    const RepeatedValidationOptions& options) {
    if (schedule.schema_version != "optimization-repeated-schedule/v1") {
        throw std::invalid_argument("invalid repeated schedule schema");
    }
    if (schedule.repetitions < 2) {
        throw std::invalid_argument("invalid repeated schedule repetitions");
    }
    if (!std::isfinite(options.minimum_improvement_ratio) ||
        options.minimum_improvement_ratio < 0.0 ||
        options.minimum_improvement_ratio > 1.0) {
        throw std::invalid_argument(
            "minimum improvement ratio must be between zero and one");
    }
    if (!std::isfinite(options.minimum_complete_trace_rate_delta) ||
        options.minimum_complete_trace_rate_delta < -1.0 ||
        options.minimum_complete_trace_rate_delta > 0.0) {
        throw std::invalid_argument(
            "minimum complete trace rate delta must be between minus one and zero");
    }
    validate_bootstrap_options(options.bootstrap);

    const RepeatedConfiguration* baseline = nullptr;
    std::map<std::string, const RepeatedConfiguration*> known;
    std::vector<const RepeatedConfiguration*> candidates;
    for (const auto& configuration : schedule.configurations) {
        if (configuration.config_id.empty() ||
            !known.emplace(configuration.config_id, &configuration).second) {
            throw std::invalid_argument(
                "repeated schedule has invalid configuration IDs");
        }
        if (configuration.role == ConfigurationRole::Baseline) {
            if (baseline != nullptr) {
                throw std::invalid_argument(
                    "repeated schedule requires one baseline");
            }
            baseline = &configuration;
        } else {
            candidates.push_back(&configuration);
        }
    }
    if (baseline == nullptr) {
        throw std::invalid_argument("repeated schedule requires one baseline");
    }

    using TrialKey = std::pair<std::size_t, std::string>;
    std::map<TrialKey, const RepeatedTrialRecord*> indexed;
    for (const auto& record : records) {
        const auto expected = known.find(record.config_id);
        if (record.block_index < 1 ||
            record.block_index > schedule.repetitions ||
            expected == known.end()) {
            throw std::invalid_argument(
                "repeated trial record does not match schedule");
        }
        if (!indexed.emplace(
                TrialKey{record.block_index, record.config_id}, &record).second) {
            throw std::invalid_argument("duplicate repeated trial record");
        }
        if (record.role != expected->second->role ||
            record.candidate_config != expected->second->candidate_config) {
            throw std::invalid_argument(
                "repeated trial record configuration mismatch");
        }
        if (record.status == TrialStatus::Succeeded) {
            (void)record_objective(record);
            (void)record_rate(record);
        }
    }

    std::vector<RepeatedCandidateValidation> results;
    results.reserve(candidates.size());
    for (std::size_t candidate_index = 0;
         candidate_index < candidates.size(); ++candidate_index) {
        const auto& candidate = *candidates[candidate_index];
        std::vector<double> improvements;
        std::vector<double> completeness_deltas;
        std::vector<double> candidate_objectives;
        std::vector<PairResult> pairs;
        pairs.reserve(schedule.repetitions);
        std::size_t failed = 0;
        std::size_t missing = 0;

        for (std::size_t block = 1; block <= schedule.repetitions; ++block) {
            const auto baseline_it = indexed.find({block, baseline->config_id});
            const auto candidate_it = indexed.find({block, candidate.config_id});
            if (baseline_it == indexed.end() || candidate_it == indexed.end()) {
                ++missing;
                pairs.push_back({block, PairStatus::Missing, {}, {}});
                continue;
            }
            const auto& baseline_record = *baseline_it->second;
            const auto& candidate_record = *candidate_it->second;
            if (baseline_record.status != TrialStatus::Succeeded ||
                candidate_record.status != TrialStatus::Succeeded) {
                ++failed;
                pairs.push_back({block, PairStatus::Failed, {}, {}});
                continue;
            }
            const double baseline_value = record_objective(baseline_record);
            const double candidate_value = record_objective(candidate_record);
            const double improvement =
                (baseline_value - candidate_value) / baseline_value;
            const double completeness_delta =
                record_rate(candidate_record) - record_rate(baseline_record);
            improvements.push_back(improvement);
            completeness_deltas.push_back(completeness_delta);
            candidate_objectives.push_back(candidate_value);
            pairs.push_back({
                block,
                PairStatus::Succeeded,
                improvement,
                completeness_delta,
            });
        }

        BootstrapOptions bootstrap = options.bootstrap;
        bootstrap.seed += candidate_index + 1;
        const auto improvement_interval =
            percentile_bootstrap_interval(improvements, bootstrap);
        const auto completeness_interval =
            percentile_bootstrap_interval(completeness_deltas, bootstrap);

        std::string reason;
        if (improvements.size() != schedule.repetitions) {
            reason = "incomplete_repeated_evidence";
        } else if (!completeness_interval.lower.has_value() ||
                   *completeness_interval.lower <
                       options.minimum_complete_trace_rate_delta) {
            reason = "complete_trace_rate_regression_uncertain";
        } else if (!improvement_interval.lower.has_value() ||
                   *improvement_interval.lower <
                       options.minimum_improvement_ratio) {
            reason = "improvement_uncertain";
        }

        RepeatedCandidateValidation result;
        result.config_index = candidate.config_index;
        result.config_id = candidate.config_id;
        result.candidate_config = candidate.candidate_config;
        result.decision = reason.empty()
            ? ValidationDecision::Accept
            : ValidationDecision::Reject;
        result.reason_code = std::move(reason);
        result.rollback_required = !result.reason_code.empty();
        result.planned_pair_count = schedule.repetitions;
        result.successful_pair_count = improvements.size();
        result.failed_pair_count = failed;
        result.missing_pair_count = missing;
        result.confidence_level = options.bootstrap.confidence_level;
        result.bootstrap_resamples = options.bootstrap.resamples;
        result.minimum_improvement_ratio = options.minimum_improvement_ratio;
        result.minimum_complete_trace_rate_delta =
            options.minimum_complete_trace_rate_delta;
        result.improvement_ratio = improvement_interval;
        result.complete_trace_rate_delta = completeness_interval;
        if (!candidate_objectives.empty()) {
            result.median_candidate_objective_ns =
                median(candidate_objectives);
        }
        result.pairs = std::move(pairs);
        results.push_back(std::move(result));
    }
    return results;
}

}  // namespace robotraceopt::optimizer
