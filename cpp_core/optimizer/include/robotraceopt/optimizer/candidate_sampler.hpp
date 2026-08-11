#pragma once

#include "robotraceopt/optimizer/types.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace robotraceopt::optimizer {

enum class ActionKind { Boolean, Integer };

struct ActionSpec {
    ActionId action_id{};
    ActionKind kind{ActionKind::Integer};
    std::int64_t minimum{};
    std::int64_t maximum{};
    DiagnosisCause cause{};
};

const ActionSpec& action_for_cause(DiagnosisCause cause);
void validate_candidate(
    DiagnosisCause cause,
    const CandidateConfiguration& candidate);

// The guided sampler is an evenly spaced deterministic grid. The seed is part
// of the API for parity with Python and future randomized policies; it does not
// alter this policy's output.
std::vector<CandidateConfiguration> sample_candidates(
    DiagnosisCause cause,
    std::size_t limit,
    std::uint64_t seed = 0);

}  // namespace robotraceopt::optimizer
