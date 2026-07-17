#pragma once

#include <cstdint>
#include <sstream>
#include <string>

namespace service_runtime_demo
{

inline bool is_faulted_sequence(const uint64_t sequence, const uint64_t fault_every_n)
{
  return fault_every_n > 0 && sequence % fault_every_n == 0;
}

inline uint64_t context_sequence(const uint64_t sequence, const uint64_t fault_every_n)
{
  return is_faulted_sequence(sequence, fault_every_n) ? 100000U + sequence : sequence;
}

inline std::string make_payload_id(const std::string & source, const uint64_t sequence)
{
  return source + ":" + std::to_string(sequence);
}

inline std::string make_trace_id(
  const std::string & source,
  const int64_t timestamp_ns,
  const uint64_t sequence)
{
  std::ostringstream stream;
  stream << "trace_" << source << "_" << timestamp_ns << "_" << sequence;
  return stream.str();
}

}  // namespace service_runtime_demo
