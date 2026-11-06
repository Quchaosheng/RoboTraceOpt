#include <cstdint>

#include "gtest/gtest.h"
#include "robot_action_pkg/goal_deadline.hpp"

namespace
{

using robot_action_pkg::GoalDeadline;

GoalDeadline deadline(int64_t timeout_ms)
{
  GoalDeadline value;
  value.start_ns = 1'000'000;
  value.timeout_ns = timeout_ms * 1'000'000;
  return value;
}

TEST(GoalDeadline, ZeroTimeoutMeansNoDeadline)
{
  const auto value = deadline(0);

  EXPECT_FALSE(value.enabled());
  EXPECT_FALSE(value.expired(value.start_ns + 10'000'000'000LL));
  EXPECT_EQ(value.next_wait_ns(value.start_ns, 50'000'000, 25'000'000), 25'000'000);
}

TEST(GoalDeadline, ExpiryUsesElapsedMonotonicTime)
{
  const auto value = deadline(10);

  EXPECT_FALSE(value.expired(value.start_ns + 9'999'999));
  EXPECT_TRUE(value.expired(value.start_ns + 10'000'000));
  EXPECT_TRUE(value.expired(value.start_ns + 60'000'000));
}

TEST(GoalDeadline, WaitsAreCappedByTheRemainingBudget)
{
  const auto value = deadline(10);

  // A full feedback period would overshoot the 10 ms budget.
  EXPECT_EQ(value.next_wait_ns(value.start_ns, 100'000'000, 50'000'000), 10'000'000);
  // After 6 ms only 4 ms of budget is left.
  EXPECT_EQ(
    value.next_wait_ns(value.start_ns + 6'000'000, 100'000'000, 50'000'000), 4'000'000);
  // No budget left: the loop must not sleep at all.
  EXPECT_EQ(
    value.next_wait_ns(value.start_ns + 10'000'000, 100'000'000, 50'000'000), 0);
}

TEST(GoalDeadline, WaitNeverExceedsRemainingWork)
{
  const auto value = deadline(0);

  EXPECT_EQ(value.next_wait_ns(value.start_ns, 3'000'000, 50'000'000), 3'000'000);
  EXPECT_EQ(value.next_wait_ns(value.start_ns, 0, 50'000'000), 0);
  EXPECT_EQ(value.next_wait_ns(value.start_ns, -5, 50'000'000), 0);
}

TEST(GoalDeadline, SlowSleepCannotBeHiddenByRequestedDuration)
{
  // Regression: `action_delay=20, feedback=50, timeout=10` used to report
  // success because elapsed counted the requested 20 ms sleep at once.
  const auto value = deadline(10);
  const int64_t work_end = value.start_ns + 20'000'000;
  int64_t now = value.start_ns;
  int64_t waited = 0;

  while (now < work_end) {
    if (value.expired(now)) {
      break;
    }
    const int64_t wait = value.next_wait_ns(now, work_end - now, 50'000'000);
    ASSERT_GT(wait, 0);
    now += wait;
    waited += wait;
  }

  EXPECT_TRUE(value.expired(now));
  EXPECT_LE(waited, 10'000'000);
}

}  // namespace
