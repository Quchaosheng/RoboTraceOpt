#include "robotraceopt/optimizer/candidate_sampler.hpp"
#include "robotraceopt/optimizer/runtime_objective.hpp"
#include "robotraceopt/optimizer/validation.hpp"

#include <cmath>
#include <cstdint>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace opt = robotraceopt::optimizer;

namespace {

int failures = 0;

void check(bool condition, const char* expression, int line) {
    if (!condition) {
        std::cerr << "line " << line << ": check failed: " << expression << '\n';
        ++failures;
    }
}

#define CHECK(expression) check((expression), #expression, __LINE__)

void check_near(double actual, double expected, double tolerance, int line) {
    if (std::abs(actual - expected) > tolerance) {
        std::cerr << "line " << line << ": expected " << expected
                  << ", got " << actual << '\n';
        ++failures;
    }
}

#define CHECK_NEAR(actual, expected, tolerance) \
    check_near((actual), (expected), (tolerance), __LINE__)

void check_throws(
    const std::function<void()>& callable,
    const std::string& expected_message,
    int line) {
    try {
        callable();
        std::cerr << "line " << line << ": expected invalid_argument\n";
        ++failures;
    } catch (const std::invalid_argument& error) {
        if (std::string(error.what()).find(expected_message) == std::string::npos) {
            std::cerr << "line " << line << ": unexpected error: "
                      << error.what() << '\n';
            ++failures;
        }
    } catch (...) {
        std::cerr << "line " << line << ": unexpected exception type\n";
        ++failures;
    }
}

#define CHECK_THROWS(callable, message) \
    check_throws((callable), (message), __LINE__)

opt::RuntimeReport report(double value = 100.0, double rate = 1.0) {
    opt::RuntimeReport result;
    result.schema_version = "service-blocking-evidence/v1";
    result.metrics_ns = {
        {"request_response_elapsed_ns", {{"p95", value}}},
    };
    result.complete_trace_rate = rate;
    result.development_only = false;
    result.formal_inference_allowed = true;
    return result;
}

opt::CandidateConfiguration threads(std::int64_t value) {
    return {opt::ActionId::ExecutorThreads, value};
}

opt::RepeatedSchedule schedule() {
    return {
        "optimization-repeated-schedule/v1",
        5,
        {
            {0, "cfg_baseline", opt::ConfigurationRole::Baseline, threads(1)},
            {1, "cfg_candidate", opt::ConfigurationRole::Candidate, threads(2)},
        },
    };
}

std::vector<opt::RepeatedTrialRecord> records(
    const std::vector<double>& candidate_values = {80, 88, 72, 84, 76},
    const std::vector<double>& candidate_rates = {1, 1, 1, 1, 1}) {
    const std::vector<double> baseline_values = {100, 110, 90, 105, 95};
    std::vector<opt::RepeatedTrialRecord> result;
    for (std::size_t index = 0; index < baseline_values.size(); ++index) {
        const auto block = index + 1;
        result.push_back({
            block,
            "cfg_baseline",
            opt::ConfigurationRole::Baseline,
            threads(1),
            opt::TrialStatus::Succeeded,
            baseline_values[index],
            1.0,
        });
        result.push_back({
            block,
            "cfg_candidate",
            opt::ConfigurationRole::Candidate,
            threads(2),
            opt::TrialStatus::Succeeded,
            candidate_values[index],
            candidate_rates[index],
        });
    }
    return result;
}

opt::RepeatedValidationOptions repeated_options() {
    return {0.10, 0.0, {0.95, 1000, 17}};
}

void test_runtime_objective() {
    const auto objective = opt::runtime_objective(
        report(120.0, 0.95), "request_response_elapsed_ns", "p95");
    CHECK_NEAR(objective.objective_value_ns, 120.0, 1e-12);
    CHECK_NEAR(objective.complete_trace_rate, 0.95, 1e-12);
    CHECK(objective.formal_optimization_allowed);
    CHECK(objective.source_schema_version == "service-blocking-evidence/v1");

    auto counted = report();
    counted.complete_trace_rate.reset();
    counted.complete_trace_count = 8;
    counted.observed_trace_count = 10;
    const auto derived = opt::runtime_objective(
        counted, "request_response_elapsed_ns", "p95");
    CHECK_NEAR(derived.complete_trace_rate, 0.8, 1e-12);

    auto development = report();
    development.development_only = true;
    CHECK(!opt::runtime_objective(
        development, "request_response_elapsed_ns", "p95")
        .formal_optimization_allowed);

    auto missing = report();
    missing.metrics_ns.clear();
    CHECK_THROWS(
        [&] {
            (void)opt::runtime_objective(
                missing, "request_response_elapsed_ns", "p95");
        },
        "missing");
    auto invalid = report();
    invalid.complete_trace_rate = std::numeric_limits<double>::quiet_NaN();
    CHECK_THROWS(
        [&] {
            (void)opt::runtime_objective(
                invalid, "request_response_elapsed_ns", "p95");
        },
        "complete_trace_rate");
}

void test_candidate_sampler() {
    const auto first = opt::sample_candidates(
        opt::DiagnosisCause::BlockingSyscallIo, 3, 7);
    const auto second = opt::sample_candidates(
        opt::DiagnosisCause::BlockingSyscallIo, 3, 7);
    CHECK(first == second);
    CHECK(first.size() == 3);
    CHECK(std::get<std::int64_t>(first[0].value) == 0);
    CHECK(std::get<std::int64_t>(first[1].value) == 50);
    CHECK(std::get<std::int64_t>(first[2].value) == 100);

    // The midpoint 2.5 rounds to even, matching Python round().
    const auto executor =
        opt::sample_candidates(opt::DiagnosisCause::ExecutorQueueing, 3, 99);
    CHECK(std::get<std::int64_t>(executor[0].value) == 1);
    CHECK(std::get<std::int64_t>(executor[1].value) == 2);
    CHECK(std::get<std::int64_t>(executor[2].value) == 4);
    CHECK(opt::diagnosis_cause_from_string("executor_queueing") ==
          opt::DiagnosisCause::ExecutorQueueing);
    CHECK(std::string(opt::to_string(opt::ActionId::ExecutorThreads)) ==
          "executor_threads");
    CHECK_THROWS(
        [] {
            (void)opt::sample_candidates(
                opt::DiagnosisCause::ExecutorQueueing, 0, 1);
        },
        "limit");
    CHECK_THROWS(
        [] {
            opt::validate_candidate(
                opt::DiagnosisCause::ExecutorQueueing,
                {opt::ActionId::ExecutorThreads, std::int64_t{5}});
        },
        "bounds");
}

void test_bootstrap() {
    const opt::BootstrapOptions options{0.95, 1000, 123};
    const auto first = opt::percentile_bootstrap_interval(
        {0.20, 0.15, 0.25, 0.18, 0.22}, options);
    const auto second = opt::percentile_bootstrap_interval(
        {0.20, 0.15, 0.25, 0.18, 0.22}, options);
    CHECK(first.estimate == second.estimate);
    CHECK(first.lower == second.lower);
    CHECK(first.upper == second.upper);
    CHECK_NEAR(*first.estimate, 0.20, 1e-12);
    CHECK(*first.lower <= *first.estimate);
    CHECK(*first.upper >= *first.estimate);

    const auto one = opt::percentile_bootstrap_interval({4.0}, options);
    CHECK(one.estimate == 4.0);
    CHECK(!one.lower.has_value());
    CHECK(!one.upper.has_value());
    const auto empty = opt::percentile_bootstrap_interval({}, options);
    CHECK(!empty.estimate.has_value());
    CHECK_THROWS(
        [] {
            (void)opt::percentile_bootstrap_interval(
                {1.0, 2.0}, {0.95, 99, 1});
        },
        "at least 100");
}

void test_single_candidate_validation() {
    CHECK(std::string(opt::CandidateValidationResult::schema_version) ==
          "candidate-validation/v1");
    const auto baseline = opt::runtime_objective(
        report(100), "request_response_elapsed_ns", "p95");
    const auto candidate = opt::runtime_objective(
        report(80), "request_response_elapsed_ns", "p95");
    const auto accepted = opt::validate_candidate_objectives(
        baseline, candidate, {0.10, 0.0, true});
    CHECK(accepted.decision == opt::ValidationDecision::Accept);
    CHECK_NEAR(accepted.improvement_ratio, 0.2, 1e-12);
    CHECK(!accepted.rollback_required);

    auto development = candidate;
    development.formal_optimization_allowed = false;
    const auto rejected = opt::validate_candidate_objectives(
        baseline, development, {0.10, 0.0, true});
    CHECK(rejected.reason_code == "formal_evidence_required");
}

void test_repeated_candidate_validation() {
    CHECK(std::string(opt::RepeatedCandidateValidation::schema_version) ==
          "repeated-candidate-validation/v1");
    const auto accepted = opt::evaluate_repeated_candidates(
        schedule(), records(), repeated_options());
    CHECK(accepted.size() == 1);
    CHECK(accepted[0].decision == opt::ValidationDecision::Accept);
    CHECK(accepted[0].reason_code.empty());
    CHECK(accepted[0].successful_pair_count == 5);
    CHECK(*accepted[0].improvement_ratio.lower >= 0.10);
    CHECK(*accepted[0].complete_trace_rate_delta.lower >= 0.0);

    const auto uncertain = opt::evaluate_repeated_candidates(
        schedule(), records({80, 132, 81, 115.5, 95}), repeated_options());
    CHECK(uncertain[0].decision == opt::ValidationDecision::Reject);
    CHECK(uncertain[0].reason_code == "improvement_uncertain");

    const auto completeness = opt::evaluate_repeated_candidates(
        schedule(), records({80, 88, 72, 84, 76}, {1, 0.9, 1, 0.9, 1}),
        repeated_options());
    CHECK(completeness[0].reason_code ==
          "complete_trace_rate_regression_uncertain");

    auto failed_records = records();
    failed_records[5].status = opt::TrialStatus::Failed;
    failed_records[5].objective_value_ns.reset();
    failed_records[5].complete_trace_rate.reset();
    const auto incomplete = opt::evaluate_repeated_candidates(
        schedule(), failed_records, repeated_options());
    CHECK(incomplete[0].reason_code == "incomplete_repeated_evidence");
    CHECK(incomplete[0].successful_pair_count == 4);
    CHECK(incomplete[0].failed_pair_count == 1);

    auto duplicate = records();
    duplicate.push_back(duplicate.front());
    CHECK_THROWS(
        [&] {
            (void)opt::evaluate_repeated_candidates(
                schedule(), duplicate, repeated_options());
        },
        "duplicate repeated trial record");

    auto invalid = records();
    invalid.front().objective_value_ns = 0.0;
    CHECK_THROWS(
        [&] {
            (void)opt::evaluate_repeated_candidates(
                schedule(), invalid, repeated_options());
        },
        "objective");
}

}  // namespace

int main() {
    test_runtime_objective();
    test_candidate_sampler();
    test_bootstrap();
    test_single_candidate_validation();
    test_repeated_candidate_validation();
    if (failures != 0) {
        std::cerr << failures << " test check(s) failed\n";
        return 1;
    }
    std::cout << "all optimizer checks passed\n";
    return 0;
}
