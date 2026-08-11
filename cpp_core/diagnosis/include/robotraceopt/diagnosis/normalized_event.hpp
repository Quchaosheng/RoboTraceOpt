#pragma once

#include <cstdint>
#include <map>
#include <string>
#include <variant>
#include <vector>

namespace robotraceopt::diagnosis {

using AttributeValue =
    std::variant<std::int64_t, double, bool, std::string, std::vector<std::int64_t>>;
using AttributeMap = std::map<std::string, AttributeValue>;

// Source-independent event. Adapters own parsing and conversion into this type.
struct NormalizedEvent {
    std::string event_id;
    std::string source;
    std::string event_type;
    std::int64_t timestamp_ns{0};
    std::string clock_id;
    std::string trace_id;
    std::int64_t sequence_id{0};
    std::string stage;
    std::int64_t pid{0};
    std::int64_t tid{0};
    std::string host_id;
    AttributeMap attributes;
    AttributeMap provenance;
};

}  // namespace robotraceopt::diagnosis
