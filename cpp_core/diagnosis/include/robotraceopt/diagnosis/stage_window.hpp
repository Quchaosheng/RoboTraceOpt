#pragma once

#include "robotraceopt/diagnosis/normalized_event.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace robotraceopt::diagnosis {

struct StageWindow {
    std::string window_id;
    std::string trace_id;
    std::int64_t sequence_id{0};
    std::string stage;
    std::string source_node;
    std::int64_t pid{0};
    std::vector<std::int64_t> tids;
    std::string host_id;
    std::string clock_id;
    std::int64_t start_ns{0};
    std::int64_t end_ns{0};
    std::string start_event_id;
    std::string end_event_id;

    [[nodiscard]] bool contains(std::int64_t timestamp_ns) const noexcept {
        return start_ns <= timestamp_ns && timestamp_ns <= end_ns;
    }
};

// Throws std::invalid_argument for incomplete RuntimeEvent identity, duplicate
// RuntimeEvent ids, invalid duration_ns, or non-monotonic grouped events.
[[nodiscard]] std::vector<StageWindow> build_stage_windows(
    const std::vector<NormalizedEvent>& events);

}  // namespace robotraceopt::diagnosis
