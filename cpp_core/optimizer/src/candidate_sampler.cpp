#include "robotraceopt/optimizer/candidate_sampler.hpp"

#include <algorithm>
#include <array>
#include <stdexcept>

namespace robotraceopt::optimizer {
namespace {

constexpr std::array<ActionSpec, 6> kActions{{
    {ActionId::PlannerDelayMs, ActionKind::Integer, 0, 100,
     DiagnosisCause::ApplicationComputeDelay},
    {ActionId::ExecutorThreads, ActionKind::Integer, 1, 4,
     DiagnosisCause::ExecutorQueueing},
    {ActionId::FrameQosDepth, ActionKind::Integer, 1, 10,
     DiagnosisCause::DdsCommunicationDelay},
    {ActionId::ServerDelayMs, ActionKind::Integer, 0, 100,
     DiagnosisCause::BlockingSyscallIo},
    {ActionId::TargetCpu, ActionKind::Integer, 0, 255,
     DiagnosisCause::SchedulingDelay},
    {ActionId::AckTimeoutMs, ActionKind::Integer, 1, 200,
     DiagnosisCause::CanAckFailure},
}};

std::int64_t grid_value(
    std::int64_t lower,
    std::int64_t upper,
    std::size_t index,
    std::size_t count) {
    if (count == 1) {
        return lower;
    }
    const auto span = static_cast<std::uint64_t>(upper - lower);
    const auto denominator = static_cast<std::uint64_t>(count - 1);
    const auto numerator = static_cast<std::uint64_t>(lower) * denominator +
        static_cast<std::uint64_t>(index) * span;
    auto quotient = numerator / denominator;
    const auto remainder = numerator % denominator;

    // Python round() uses ties-to-even. Keeping this exact integer operation
    // preserves grid semantics without relying on floating-point rounding mode.
    if (remainder > denominator / 2 ||
        (denominator % 2 == 0 && remainder == denominator / 2 &&
         quotient % 2 == 1)) {
        ++quotient;
    }
    return static_cast<std::int64_t>(quotient);
}

}  // namespace

const char* to_string(DiagnosisCause cause) {
    switch (cause) {
        case DiagnosisCause::ApplicationComputeDelay:
            return "application_compute_delay";
        case DiagnosisCause::ExecutorQueueing:
            return "executor_queueing";
        case DiagnosisCause::DdsCommunicationDelay:
            return "dds_communication_delay";
        case DiagnosisCause::BlockingSyscallIo:
            return "blocking_syscall_io";
        case DiagnosisCause::SchedulingDelay:
            return "scheduling_delay";
        case DiagnosisCause::CanAckFailure:
            return "can_ack_failure";
    }
    throw std::invalid_argument("unknown cause");
}

const char* to_string(ActionId action) {
    switch (action) {
        case ActionId::PlannerDelayMs:
            return "planner_delay_ms";
        case ActionId::ExecutorThreads:
            return "executor_threads";
        case ActionId::FrameQosDepth:
            return "frame_qos_depth";
        case ActionId::ServerDelayMs:
            return "server_delay_ms";
        case ActionId::TargetCpu:
            return "target_cpu";
        case ActionId::AckTimeoutMs:
            return "ack_timeout_ms";
    }
    throw std::invalid_argument("unknown action");
}

DiagnosisCause diagnosis_cause_from_string(const std::string& value) {
    for (const auto& action : kActions) {
        if (value == to_string(action.cause)) {
            return action.cause;
        }
    }
    throw std::invalid_argument("unknown cause: " + value);
}

ActionId action_id_from_string(const std::string& value) {
    for (const auto& action : kActions) {
        if (value == to_string(action.action_id)) {
            return action.action_id;
        }
    }
    throw std::invalid_argument("unknown action: " + value);
}

const ActionSpec& action_for_cause(DiagnosisCause cause) {
    const auto found = std::find_if(
        kActions.begin(), kActions.end(),
        [cause](const ActionSpec& action) { return action.cause == cause; });
    if (found == kActions.end()) {
        throw std::invalid_argument("unknown cause");
    }
    return *found;
}

void validate_candidate(
    DiagnosisCause cause,
    const CandidateConfiguration& candidate) {
    const auto& action = action_for_cause(cause);
    if (candidate.action_id != action.action_id) {
        throw std::invalid_argument(
            std::string("action ") + to_string(candidate.action_id) +
            " is not allowed for cause " + to_string(cause));
    }
    if (action.kind == ActionKind::Boolean) {
        if (!std::holds_alternative<bool>(candidate.value)) {
            throw std::invalid_argument("action expects boolean");
        }
        return;
    }
    const auto value = std::get_if<std::int64_t>(&candidate.value);
    if (value == nullptr) {
        throw std::invalid_argument("action expects integer");
    }
    if (*value < action.minimum || *value > action.maximum) {
        throw std::invalid_argument("action is outside bounds");
    }
}

std::vector<CandidateConfiguration> sample_candidates(
    DiagnosisCause cause,
    std::size_t limit,
    std::uint64_t seed) {
    (void)seed;
    if (limit == 0) {
        throw std::invalid_argument("limit must be positive");
    }
    const auto& action = action_for_cause(cause);
    std::vector<CandidateConfiguration> result;
    if (action.kind == ActionKind::Boolean) {
        result.push_back({action.action_id, false});
        if (limit > 1) {
            result.push_back({action.action_id, true});
        }
        return result;
    }

    const auto available = static_cast<std::size_t>(
        static_cast<std::uint64_t>(action.maximum - action.minimum) + 1U);
    const auto count = std::min(limit, available);
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        CandidateConfiguration candidate{
            action.action_id,
            grid_value(action.minimum, action.maximum, index, count),
        };
        validate_candidate(cause, candidate);
        result.push_back(std::move(candidate));
    }
    return result;
}

}  // namespace robotraceopt::optimizer
