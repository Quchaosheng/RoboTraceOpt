#pragma once

#include <cstdint>
#include <string>
#include <variant>

namespace robotraceopt::optimizer {

enum class DiagnosisCause {
    ApplicationComputeDelay,
    ExecutorQueueing,
    DdsCommunicationDelay,
    BlockingSyscallIo,
    SchedulingDelay,
    CanAckFailure,
};

enum class ActionId {
    PlannerDelayMs,
    ExecutorThreads,
    FrameQosDepth,
    ServerDelayMs,
    TargetCpu,
    AckTimeoutMs,
};

using ActionValue = std::variant<bool, std::int64_t>;

struct CandidateConfiguration {
    ActionId action_id{};
    ActionValue value{std::int64_t{0}};
};

inline bool operator==(
    const CandidateConfiguration& left,
    const CandidateConfiguration& right) noexcept {
    return left.action_id == right.action_id && left.value == right.value;
}

inline bool operator!=(
    const CandidateConfiguration& left,
    const CandidateConfiguration& right) noexcept {
    return !(left == right);
}

const char* to_string(DiagnosisCause cause);
const char* to_string(ActionId action);
DiagnosisCause diagnosis_cause_from_string(const std::string& value);
ActionId action_id_from_string(const std::string& value);

}  // namespace robotraceopt::optimizer
