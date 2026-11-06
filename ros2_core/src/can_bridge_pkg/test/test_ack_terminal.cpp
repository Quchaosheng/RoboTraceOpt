#include <string>

#include "can_bridge_pkg/can_ack_terminal.hpp"
#include "gtest/gtest.h"

namespace
{

using can_bridge_pkg::AckTerminal;
using can_bridge_pkg::plan_ack_terminal;

TEST(AckTerminal, EveryConfigurationSchedulesExactlyOneTerminal)
{
  struct Case
  {
    std::string ack_mode;
    std::string policy;
    uint32_t retry_count;
    int64_t delay_ms;
    int64_t timeout_ms;
    AckTerminal expected;
  };
  const Case cases[] = {
    {"mock", "success", 0, 0, 50, AckTerminal::kAck},
    {"mock", "success", 0, 49, 50, AckTerminal::kAck},
    {"mock", "success", 0, 50, 50, AckTerminal::kTimeout},
    {"mock", "success", 0, 60, 50, AckTerminal::kTimeout},
    {"mock", "drop_first", 0, 5, 50, AckTerminal::kTimeout},
    {"mock", "drop_first", 1, 5, 50, AckTerminal::kAck},
    {"mock", "drop", 0, 5, 50, AckTerminal::kTimeout},
    {"mock", "delayed", 0, 5, 50, AckTerminal::kTimeout},
    {"mock", "delayed", 0, 500, 50, AckTerminal::kTimeout},
    {"socketcan", "success", 0, 5, 50, AckTerminal::kTimeout},
    {"disabled", "success", 0, 5, 50, AckTerminal::kTimeout},
  };

  for (const auto & item : cases) {
    EXPECT_EQ(
      plan_ack_terminal(
        item.ack_mode, item.policy, item.retry_count, item.delay_ms, item.timeout_ms),
      item.expected)
      << "ack_mode=" << item.ack_mode << " policy=" << item.policy
      << " retry=" << item.retry_count << " delay=" << item.delay_ms
      << " timeout=" << item.timeout_ms;
  }
}

TEST(AckTerminal, MockAckSlowerThanTheTimeoutStillTerminates)
{
  // Regression: both the ACK and the timeout guard used to decline here, so the
  // command ended with no terminal event at all.
  EXPECT_EQ(
    plan_ack_terminal("mock", "success", 0, 60, 50), AckTerminal::kTimeout);
}

TEST(AckTerminal, DelayedPolicyAlwaysOverridesTheConfiguredDelay)
{
  for (const int64_t configured : {0, 5, 40}) {
    EXPECT_EQ(
      plan_ack_terminal("mock", "delayed", 0, configured, 50), AckTerminal::kTimeout)
      << "configured delay " << configured;
  }
}

}  // namespace
