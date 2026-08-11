#include "robotraceopt/diagnosis/association.hpp"

#include <algorithm>
#include <cstdlib>
#include <limits>
#include <set>
#include <stdexcept>
#include <tuple>

namespace robotraceopt::diagnosis {
namespace {

bool ends_with(const std::string& value, std::string_view suffix) {
    return value.size() >= suffix.size() &&
           value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}

AssociationDecision base_decision(
    const NormalizedEvent& event, AssociationStatus status, std::string reason) {
    AssociationDecision result;
    result.event_id = event.event_id;
    result.status = status;
    result.reason_code = std::move(reason);
    result.source = event.source;
    result.event_type = event.event_type;
    return result;
}

AssociationDecision accepted(
    const NormalizedEvent& event,
    const StageWindow& window,
    std::string reason,
    int score,
    std::size_t candidate_count) {
    auto result = base_decision(event, AssociationStatus::Accepted, std::move(reason));
    result.trace_id = window.trace_id;
    result.sequence_id = window.sequence_id;
    result.stage = window.stage;
    result.window_id = window.window_id;
    result.score = score;
    result.candidate_count = candidate_count;
    return result;
}

struct Admission {
    std::vector<const StageWindow*> windows;
    std::string rejection;
};

Admission admitted_windows(
    const NormalizedEvent& event, const std::vector<StageWindow>& windows) {
    Admission admitted;
    for (const auto& window : windows) {
        if (window.host_id == event.host_id) {
            admitted.windows.push_back(&window);
        }
    }
    if (admitted.windows.empty()) {
        admitted.rejection = "host_mismatch";
        return admitted;
    }
    admitted.windows.erase(
        std::remove_if(
            admitted.windows.begin(), admitted.windows.end(), [&](const auto* window) {
                return window->clock_id != event.clock_id;
            }),
        admitted.windows.end());
    if (admitted.windows.empty()) {
        admitted.rejection = "clock_domain_mismatch";
    }
    return admitted;
}

std::uint64_t midpoint_distance(std::int64_t timestamp, const StageWindow& window) {
    const auto remainder = window.start_ns % 2 + window.end_ns % 2;
    const auto floor_adjustment = remainder < 0 && remainder % 2 != 0 ? -1 : 0;
    const auto midpoint = window.start_ns / 2 + window.end_ns / 2 + remainder / 2 +
                          floor_adjustment;
    if (timestamp >= midpoint) {
        return static_cast<std::uint64_t>(timestamp) - static_cast<std::uint64_t>(midpoint);
    }
    return static_cast<std::uint64_t>(midpoint) - static_cast<std::uint64_t>(timestamp);
}

}  // namespace

std::string_view to_string(AssociationStatus status) noexcept {
    switch (status) {
        case AssociationStatus::Accepted:
            return "accepted";
        case AssociationStatus::Ambiguous:
            return "ambiguous";
        case AssociationStatus::Rejected:
            return "rejected";
        case AssociationStatus::Unmatched:
            return "unmatched";
    }
    return "unmatched";
}

AssociationDecision associate_system_event(
    const NormalizedEvent& event, const std::vector<StageWindow>& windows) {
    if (ends_with(event.event_type, "_init") ||
        ends_with(event.event_type, "_callback_added") ||
        event.event_type == "ros2:rclcpp_callback_register" ||
        event.event_type == "ros2:rclcpp_timer_link_node") {
        return base_decision(event, AssociationStatus::Unmatched, "topology_metadata");
    }

    const auto admission = admitted_windows(event, windows);
    if (!admission.rejection.empty()) {
        return base_decision(event, AssociationStatus::Rejected, admission.rejection);
    }

    std::vector<const StageWindow*> candidates;
    for (const auto* window : admission.windows) {
        if (window->pid == event.pid && window->contains(event.timestamp_ns)) {
            candidates.push_back(window);
        }
    }
    if (candidates.empty()) {
        return base_decision(
            event, AssociationStatus::Unmatched, "no_process_time_candidate");
    }

    int best_score = 0;
    std::vector<const StageWindow*> best;
    for (const auto* window : candidates) {
        const auto exact_tid =
            std::find(window->tids.begin(), window->tids.end(), event.tid) != window->tids.end();
        const int score = exact_tid ? 2 : 1;
        if (score > best_score) {
            best_score = score;
            best.clear();
        }
        if (score == best_score) {
            best.push_back(window);
        }
    }

    std::set<std::pair<std::string, std::string>> distinct_targets;
    for (const auto* window : best) {
        distinct_targets.emplace(window->trace_id, window->stage);
    }
    if (distinct_targets.size() > 1) {
        auto result = base_decision(
            event, AssociationStatus::Ambiguous, "multiple_equal_candidates");
        result.score = best_score;
        result.candidate_count = best.size();
        return result;
    }
    const auto* selected = *std::max_element(best.begin(), best.end(), [](const auto* left,
                                                                          const auto* right) {
        return std::tie(left->start_ns, left->window_id) <
               std::tie(right->start_ns, right->window_id);
    });
    return accepted(
        event,
        *selected,
        best_score == 2 ? "pid_tid_time_match" : "pid_time_match",
        best_score,
        candidates.size());
}

AssociationDecision associate_by_timestamp(
    const NormalizedEvent& event, const std::vector<StageWindow>& windows) {
    const auto admission = admitted_windows(event, windows);
    if (!admission.rejection.empty()) {
        return base_decision(event, AssociationStatus::Rejected, admission.rejection);
    }
    std::vector<const StageWindow*> pool;
    for (const auto* window : admission.windows) {
        if (window->contains(event.timestamp_ns)) {
            pool.push_back(window);
        }
    }
    if (pool.empty()) {
        pool = admission.windows;
    }
    if (pool.empty()) {
        throw std::invalid_argument("associate_by_timestamp requires at least one window");
    }
    const auto* selected = *std::min_element(pool.begin(), pool.end(), [&](const auto* left,
                                                                          const auto* right) {
        return std::tuple{midpoint_distance(event.timestamp_ns, *left), left->window_id} <
               std::tuple{midpoint_distance(event.timestamp_ns, *right), right->window_id};
    });
    return accepted(
        event, *selected, "timestamp_only_baseline", 0, pool.size());
}

}  // namespace robotraceopt::diagnosis
