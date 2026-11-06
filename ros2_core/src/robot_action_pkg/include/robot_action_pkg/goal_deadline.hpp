#ifndef ROBOT_ACTION_PKG__GOAL_DEADLINE_HPP_
#define ROBOT_ACTION_PKG__GOAL_DEADLINE_HPP_

#include <algorithm>
#include <cstdint>

namespace robot_action_pkg
{

/// Deadline arithmetic for one goal execution.
///
/// The loop used to accumulate the *requested* sleep duration, so a `sleep_for`
/// that returned late (descheduled thread, loaded executor) was invisible and a
/// goal whose last sleep crossed the timeout still reported success. Elapsed
/// time comes from the monotonic clock instead, and every wait is capped to the
/// remaining budget.
struct GoalDeadline
{
  int64_t start_ns = 0;
  int64_t timeout_ns = 0;

  /// A non-positive timeout means "no deadline", matching `goal_timeout_ms=0`.
  bool enabled() const { return timeout_ns > 0; }

  int64_t elapsed_ns(int64_t now_ns) const { return now_ns - start_ns; }

  bool expired(int64_t now_ns) const
  {
    return enabled() && elapsed_ns(now_ns) >= timeout_ns;
  }

  /// Remaining time is never negative and never exceeds `period_ns`, so the
  /// loop cannot overshoot the deadline by a whole feedback period.
  int64_t next_wait_ns(int64_t now_ns, int64_t remaining_work_ns, int64_t period_ns) const
  {
    const int64_t wait = std::min(std::max<int64_t>(remaining_work_ns, 0), period_ns);
    if (!enabled()) {
      return wait;
    }
    const int64_t remaining_budget = std::max<int64_t>(timeout_ns - elapsed_ns(now_ns), 0);
    return std::min(wait, remaining_budget);
  }
};

}  // namespace robot_action_pkg

#endif  // ROBOT_ACTION_PKG__GOAL_DEADLINE_HPP_
