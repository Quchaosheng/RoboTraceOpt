#include "robotraceopt/optimizer/runtime_objective.hpp"

#include <cmath>
#include <stdexcept>

namespace robotraceopt::optimizer {

RuntimeObjective runtime_objective(
    const RuntimeReport& report,
    const std::string& metric,
    const std::string& quantile) {
    const auto metric_it = report.metrics_ns.find(metric);
    if (metric_it == report.metrics_ns.end()) {
        throw std::invalid_argument("missing " + metric + " " + quantile);
    }
    const auto quantile_it = metric_it->second.find(quantile);
    if (quantile_it == metric_it->second.end()) {
        throw std::invalid_argument("missing " + metric + " " + quantile);
    }
    const double value = quantile_it->second;
    if (!std::isfinite(value) || value < 0.0) {
        throw std::invalid_argument("invalid " + metric + " " + quantile);
    }

    double rate = 0.0;
    if (report.complete_trace_rate.has_value()) {
        rate = *report.complete_trace_rate;
    } else if (
        report.complete_trace_count.has_value() &&
        report.observed_trace_count.has_value() &&
        *report.observed_trace_count > 0 &&
        *report.complete_trace_count <= *report.observed_trace_count) {
        rate = static_cast<double>(*report.complete_trace_count) /
            static_cast<double>(*report.observed_trace_count);
    } else {
        throw std::invalid_argument("invalid complete_trace_rate");
    }
    if (!std::isfinite(rate) || rate < 0.0 || rate > 1.0) {
        throw std::invalid_argument("invalid complete_trace_rate");
    }

    const bool formal =
        report.development_only.has_value() &&
        !*report.development_only &&
        report.formal_inference_allowed.has_value() &&
        *report.formal_inference_allowed;
    return RuntimeObjective{
        report.schema_version,
        metric,
        quantile,
        value,
        rate,
        formal,
    };
}

}  // namespace robotraceopt::optimizer
