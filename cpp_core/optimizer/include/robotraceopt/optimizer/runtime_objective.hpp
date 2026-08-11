#pragma once

#include <cstddef>
#include <map>
#include <optional>
#include <string>

namespace robotraceopt::optimizer {

struct RuntimeReport {
    std::string schema_version;
    std::map<std::string, std::map<std::string, double>> metrics_ns;
    std::optional<double> complete_trace_rate;
    std::optional<std::size_t> complete_trace_count;
    std::optional<std::size_t> observed_trace_count;
    std::optional<bool> development_only;
    std::optional<bool> formal_inference_allowed;
};

struct RuntimeObjective {
    static constexpr const char* schema_version = "runtime-objective/v1";

    std::string source_schema_version;
    std::string metric;
    std::string quantile;
    double objective_value_ns{};
    double complete_trace_rate{};
    bool formal_optimization_allowed{};
};

RuntimeObjective runtime_objective(
    const RuntimeReport& report,
    const std::string& metric,
    const std::string& quantile);

}  // namespace robotraceopt::optimizer
