#include <atomic>
#include <chrono>
#include <thread>

#include "ai_robot_runtime_interfaces/reaping_thread_group.hpp"
#include "gtest/gtest.h"

namespace
{

using ai_robot_runtime_interfaces::ReapingThreadGroup;

TEST(ReapingThreadGroup, FinishedWorkersAreReapedInsteadOfAccumulated)
{
  ReapingThreadGroup group;
  std::atomic_int completed{0};

  for (int index = 0; index < 50; ++index) {
    group.spawn([&completed]() { completed.fetch_add(1); });
  }
  group.close();

  EXPECT_EQ(completed.load(), 50);
  EXPECT_EQ(group.size(), 0u);
}

TEST(ReapingThreadGroup, RetainedWorkersStayBoundedAcrossManySpawns)
{
  ReapingThreadGroup group;
  std::atomic_int completed{0};

  // Each spawn reaps finished workers, so the group never holds more than the
  // work in flight rather than one handle per command for the whole run.
  for (int index = 0; index < 200; ++index) {
    group.spawn([&completed]() { completed.fetch_add(1); });
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  const auto retained = group.size();
  group.close();

  EXPECT_EQ(completed.load(), 200);
  EXPECT_LT(retained, 200u);
  EXPECT_EQ(group.size(), 0u);
}

TEST(ReapingThreadGroup, AWorkerMaySpawnAgainWithoutDeadlocking)
{
  ReapingThreadGroup group;
  std::atomic_int completed{0};

  // Mirrors the CAN retry path: the worker schedules the next attempt.
  std::function<void(int)> retry_chain = [&](int remaining) {
      completed.fetch_add(1);
      if (remaining > 0) {
        group.spawn([&retry_chain, remaining]() { retry_chain(remaining - 1); });
      }
    };
  group.spawn([&retry_chain]() { retry_chain(3); });
  // The chain is recursive across threads; wait for it before closing, which
  // is the same ordering the node uses (shutdown only after the run ends).
  for (int spin = 0; spin < 2000 && completed.load() < 4; ++spin) {
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  group.close();

  EXPECT_EQ(completed.load(), 4);
}

TEST(ReapingThreadGroup, CloseRefusesNewWorkAndIsIdempotent)
{
  ReapingThreadGroup group;
  std::atomic_int completed{0};

  group.close();
  group.spawn([&completed]() { completed.fetch_add(1); });
  group.close();

  EXPECT_EQ(completed.load(), 0);
  EXPECT_EQ(group.size(), 0u);
}

}  // namespace
