#include "robotraceopt/diagnosis/stage_window.hpp"

#include <algorithm>
#include <map>
#include <limits>
#include <set>
#include <stdexcept>
#include <tuple>
#include <utility>

namespace robotraceopt::diagnosis {
namespace {

using GroupKey =
    std::tuple<std::string, std::int64_t, std::int64_t, std::string, std::string>;

std::string scalar_to_string(const AttributeValue& value) {
    if (const auto* text = std::get_if<std::string>(&value)) {
        return *text;
    }
    if (const auto* integer = std::get_if<std::int64_t>(&value)) {
        return std::to_string(*integer);
    }
    if (const auto* real = std::get_if<double>(&value)) {
        return std::to_string(*real);
    }
    if (const auto* flag = std::get_if<bool>(&value)) {
        return *flag ? "True" : "False";
    }
    return "";
}

std::int64_t duration_for(const NormalizedEvent& event) {
    const auto found = event.attributes.find("duration_ns");
    if (found == event.attributes.end()) {
        return 0;
    }
    const auto* duration = std::get_if<std::int64_t>(&found->second);
    if (duration == nullptr || *duration < 0) {
        throw std::invalid_argument("invalid duration_ns: " + event.event_id);
    }
    return *duration;
}

}  // namespace

std::vector<StageWindow> build_stage_windows(const std::vector<NormalizedEvent>& events) {
    std::map<GroupKey, std::vector<const NormalizedEvent*>> groups;
    std::set<std::string> event_ids;

    for (const auto& event : events) {
        if (event.source != "runtime_event") {
            continue;
        }
        if (event.event_id.empty()) {
            throw std::invalid_argument("RuntimeEvent event_id must not be empty");
        }
        if (!event_ids.emplace(event.event_id).second) {
            throw std::invalid_argument("duplicate RuntimeEvent event_id: " + event.event_id);
        }
        if (event.trace_id.empty() || event.stage.empty() || event.pid <= 0 || event.tid <= 0) {
            throw std::invalid_argument("incomplete RuntimeEvent identity: " + event.event_id);
        }
        groups[{event.trace_id, event.sequence_id, event.pid, event.host_id, event.clock_id}]
            .push_back(&event);
    }

    std::vector<StageWindow> windows;
    for (auto& [key, grouped] : groups) {
        (void)key;
        std::stable_sort(grouped.begin(), grouped.end(), [](const auto* left, const auto* right) {
            return left->timestamp_ns < right->timestamp_ns;
        });
        for (std::size_t index = 0; index < grouped.size(); ++index) {
            const auto& start = *grouped[index];
            const auto* next = index + 1 < grouped.size() ? grouped[index + 1] : nullptr;
            const auto duration = duration_for(start);
            std::int64_t end_ns = next == nullptr ? start.timestamp_ns : next->timestamp_ns;
            if (next == nullptr) {
                if (duration > 0 &&
                    start.timestamp_ns > std::numeric_limits<std::int64_t>::max() - duration) {
                    throw std::invalid_argument("duration_ns overflows timestamp: " + start.event_id);
                }
                end_ns += duration;
            }
            if (end_ns < start.timestamp_ns) {
                throw std::invalid_argument("non-monotonic stage events: " + start.trace_id);
            }
            std::string source_node;
            if (const auto found = start.attributes.find("source_node");
                found != start.attributes.end()) {
                source_node = scalar_to_string(found->second);
            }
            windows.push_back(StageWindow{
                "stage-window:" + start.event_id,
                start.trace_id,
                start.sequence_id,
                start.stage,
                std::move(source_node),
                start.pid,
                {start.tid},
                start.host_id,
                start.clock_id,
                start.timestamp_ns,
                end_ns,
                start.event_id,
                next == nullptr ? start.event_id : next->event_id,
            });
        }
    }
    std::sort(windows.begin(), windows.end(), [](const auto& left, const auto& right) {
        return std::tie(left.start_ns, left.window_id) < std::tie(right.start_ns, right.window_id);
    });
    return windows;
}

}  // namespace robotraceopt::diagnosis
