#ifndef MINIMAL_RUNTIME_DEMO__COMMON_HPP_
#define MINIMAL_RUNTIME_DEMO__COMMON_HPP_

#include <chrono>
#include <cctype>
#include <cstdint>
#include <iomanip>
#include <optional>
#include <sstream>
#include <string>

#include "ai_robot_runtime_interfaces/msg/runtime_event.hpp"
#include "ai_robot_runtime_interfaces/runtime_event_identity.hpp"

namespace minimal_runtime_demo
{

struct DemoPayload
{
  std::string trace_id;
  uint64_t sequence_id;
  int64_t timestamp_ns;
};

inline int64_t get_timestamp_ns()
{
  const auto now = std::chrono::steady_clock::now().time_since_epoch();
  return std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
}

inline std::string json_escape(const std::string & value)
{
  std::ostringstream oss;
  oss << std::hex << std::setfill('0');

  for (const unsigned char ch : value) {
    switch (ch) {
      case '\"':
        oss << "\\\"";
        break;
      case '\\':
        oss << "\\\\";
        break;
      case '\b':
        oss << "\\b";
        break;
      case '\f':
        oss << "\\f";
        break;
      case '\n':
        oss << "\\n";
        break;
      case '\r':
        oss << "\\r";
        break;
      case '\t':
        oss << "\\t";
        break;
      default:
        if (ch < 0x20) {
          oss << "\\u" << std::setw(4) << static_cast<int>(ch);
        } else {
          oss << static_cast<char>(ch);
        }
        break;
    }
  }

  return oss.str();
}

inline std::string make_trace_id(const uint64_t sequence_id)
{
  std::ostringstream oss;
  oss << "trace-" << get_timestamp_ns() << "-" << sequence_id;
  return oss.str();
}

inline ai_robot_runtime_interfaces::msg::RuntimeEvent make_runtime_event(
  const std::string & trace_id,
  const uint64_t sequence_id,
  const std::string & source_node,
  const std::string & stage,
  const int64_t timestamp_ns = get_timestamp_ns(),
  const std::string & event_type = "runtime",
  const std::string & extra_json = "{}")
{
  ai_robot_runtime_interfaces::msg::RuntimeEvent event;
  event.header.trace_id = trace_id;
  event.header.sequence_id = sequence_id;
  event.header.source_node = source_node;
  event.header.stage = stage;
  event.header.timestamp_ns = timestamp_ns;
  event.event_name = stage;
  event.event_type = event_type;
  ai_robot_runtime_interfaces::populate_runtime_identity(event, "monotonic");
  event.extra_json = extra_json;
  return event;
}

inline std::string make_demo_payload(
  const std::string & trace_id,
  const uint64_t sequence_id,
  const int64_t timestamp_ns)
{
  std::ostringstream oss;
  oss << "{"
      << "\"trace_id\":\"" << json_escape(trace_id) << "\","
      << "\"sequence_id\":" << sequence_id << ","
      << "\"timestamp_ns\":" << timestamp_ns
      << "}";
  return oss.str();
}

inline std::optional<size_t> find_json_value_start(
  const std::string & json,
  const std::string & key)
{
  const auto key_token = "\"" + key + "\"";
  const auto key_pos = json.find(key_token);
  if (key_pos == std::string::npos) {
    return std::nullopt;
  }

  const auto colon_pos = json.find(':', key_pos + key_token.size());
  if (colon_pos == std::string::npos) {
    return std::nullopt;
  }

  auto value_pos = colon_pos + 1;
  while (value_pos < json.size() && std::isspace(static_cast<unsigned char>(json[value_pos]))) {
    ++value_pos;
  }

  if (value_pos >= json.size()) {
    return std::nullopt;
  }

  return value_pos;
}

inline std::optional<std::string> get_json_string_field(
  const std::string & json,
  const std::string & key)
{
  const auto value_start = find_json_value_start(json, key);
  if (!value_start.has_value() || json[*value_start] != '"') {
    return std::nullopt;
  }

  std::string value;
  bool escaping = false;
  for (auto i = *value_start + 1; i < json.size(); ++i) {
    const char ch = json[i];
    if (escaping) {
      switch (ch) {
        case '"':
        case '\\':
        case '/':
          value.push_back(ch);
          break;
        case 'b':
          value.push_back('\b');
          break;
        case 'f':
          value.push_back('\f');
          break;
        case 'n':
          value.push_back('\n');
          break;
        case 'r':
          value.push_back('\r');
          break;
        case 't':
          value.push_back('\t');
          break;
        default:
          value.push_back(ch);
          break;
      }
      escaping = false;
      continue;
    }

    if (ch == '\\') {
      escaping = true;
      continue;
    }
    if (ch == '"') {
      return value;
    }
    value.push_back(ch);
  }

  return std::nullopt;
}

inline std::optional<uint64_t> get_json_uint64_field(
  const std::string & json,
  const std::string & key)
{
  const auto value_start = find_json_value_start(json, key);
  if (!value_start.has_value()) {
    return std::nullopt;
  }

  auto end = *value_start;
  while (end < json.size() && std::isdigit(static_cast<unsigned char>(json[end]))) {
    ++end;
  }
  if (end == *value_start) {
    return std::nullopt;
  }

  return static_cast<uint64_t>(std::stoull(json.substr(*value_start, end - *value_start)));
}

inline std::optional<DemoPayload> parse_demo_payload(const std::string & json)
{
  const auto trace_id = get_json_string_field(json, "trace_id");
  const auto sequence_id = get_json_uint64_field(json, "sequence_id");
  const auto timestamp_ns = get_json_uint64_field(json, "timestamp_ns");

  if (!trace_id.has_value() || !sequence_id.has_value() || !timestamp_ns.has_value()) {
    return std::nullopt;
  }

  return DemoPayload{*trace_id, *sequence_id, static_cast<int64_t>(*timestamp_ns)};
}

}  // namespace minimal_runtime_demo

#endif  // MINIMAL_RUNTIME_DEMO__COMMON_HPP_
