#ifndef CAN_BRIDGE_PKG__CAN_ACK_TERMINAL_HPP_
#define CAN_BRIDGE_PKG__CAN_ACK_TERMINAL_HPP_

#include <algorithm>
#include <cstdint>
#include <string>

namespace can_bridge_pkg
{

enum class AckTerminal
{
  kAck,
  kTimeout,
};

/// Whether the mock responder answers this attempt at all.
inline bool mock_ack_will_arrive(
  const std::string & ack_mode,
  const std::string & mock_ack_policy,
  uint32_t retry_count)
{
  if (ack_mode != "mock") {
    return false;
  }
  if (mock_ack_policy == "drop") {
    return false;
  }
  if (mock_ack_policy == "drop_first" && retry_count == 0) {
    return false;
  }
  return true;
}

/// Delay the mock responder actually uses, including the policy override.
inline int64_t effective_mock_ack_delay_ms(
  const std::string & mock_ack_policy,
  int64_t mock_ack_delay_ms,
  int64_t ack_timeout_ms)
{
  if (mock_ack_policy == "delayed") {
    return std::max<int64_t>(mock_ack_delay_ms, ack_timeout_ms + 10);
  }
  return mock_ack_delay_ms;
}

/// Decide the single terminal timer for one send attempt.
///
/// Every attempt must end in exactly one of an ACK or a timeout. Scheduling the
/// two timers from independent guards let both decline — a mock ACK configured
/// slower than `ack_timeout_ms` produced no terminal at all — so the decision
/// lives in one function and both call sites ask it the same question.
inline AckTerminal plan_ack_terminal(
  const std::string & ack_mode,
  const std::string & mock_ack_policy,
  uint32_t retry_count,
  int64_t mock_ack_delay_ms,
  int64_t ack_timeout_ms)
{
  const bool arrives_in_time =
    mock_ack_will_arrive(ack_mode, mock_ack_policy, retry_count) &&
    effective_mock_ack_delay_ms(mock_ack_policy, mock_ack_delay_ms, ack_timeout_ms) <
    ack_timeout_ms;
  return arrives_in_time ? AckTerminal::kAck : AckTerminal::kTimeout;
}

}  // namespace can_bridge_pkg

#endif  // CAN_BRIDGE_PKG__CAN_ACK_TERMINAL_HPP_
