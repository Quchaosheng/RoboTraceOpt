#pragma once

#include "robotraceopt/diagnosis/normalized_event.hpp"
#include "robotraceopt/diagnosis/stage_window.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace robotraceopt::diagnosis {

enum class AssociationStatus { Accepted, Ambiguous, Rejected, Unmatched };

[[nodiscard]] std::string_view to_string(AssociationStatus status) noexcept;

struct AssociationDecision {
    std::string event_id;
    AssociationStatus status{AssociationStatus::Unmatched};
    std::string reason_code;
    std::string source;
    std::string event_type;
    std::string trace_id;
    std::int64_t sequence_id{0};
    std::string stage;
    std::string window_id;
    int score{0};
    std::size_t candidate_count{0};
    std::int64_t callback_handle{0};
    std::string callback_kind;
    std::string callback_name;
};

// Returns a decision for every well-formed input, including an empty window set.
[[nodiscard]] AssociationDecision associate_system_event(
    const NormalizedEvent& event, const std::vector<StageWindow>& windows);

// Compatibility baseline. Host/clock admission failures are returned as
// rejected decisions, matching associate_system_event.
[[nodiscard]] AssociationDecision associate_by_timestamp(
    const NormalizedEvent& event, const std::vector<StageWindow>& windows);

}  // namespace robotraceopt::diagnosis
