#include "vlm_planner_cpp_pkg/runtime_contract.hpp"

#include <atomic>
#include <chrono>
#include <cctype>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <utility>

namespace vlm_planner_cpp_pkg
{
namespace
{

std::string normalize(std::string value)
{
  const auto first = value.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) {
    return {};
  }
  const auto last = value.find_last_not_of(" \t\r\n");
  value = value.substr(first, last - first + 1);
  for (char & character : value) {
    character = static_cast<char>(std::tolower(static_cast<unsigned char>(character)));
  }
  return value;
}

bool valid_delay_mode(const std::string & mode)
{
  return mode == "sleep" || mode == "busy_compute";
}

}  // namespace

BackendSelection select_backend(std::string requested)
{
  requested = normalize(std::move(requested));
  if (requested == "mock") {
    return {requested, "mock", {}};
  }
  if (requested == "llm" || requested == "replay") {
    return {requested, "abstain", "cpp_backend_not_implemented"};
  }
  return {requested, "abstain", "unsupported_planner_backend"};
}

void validate_runtime_settings(const RuntimeSettings & settings)
{
  if (settings.executor_threads < 1 || settings.executor_threads > 4) {
    throw std::invalid_argument("executor_threads must be between 1 and 4");
  }
  if (settings.planner_delay_ms < 0 || settings.model_queue_delay_ms < 0) {
    throw std::invalid_argument("planner delays must be non-negative");
  }
  if (settings.executor_contention_period_ms <= 0) {
    throw std::invalid_argument("executor_contention_period_ms must be positive");
  }
  if (settings.executor_contention_load_ms < 0) {
    throw std::invalid_argument("executor_contention_load_ms must be non-negative");
  }
  if (settings.observation_ttl_ms <= 0) {
    throw std::invalid_argument("observation_ttl_ms must be positive");
  }
  if (!valid_delay_mode(settings.planner_delay_mode) ||
    !valid_delay_mode(settings.model_queue_delay_mode))
  {
    throw std::invalid_argument("delay mode must be sleep or busy_compute");
  }
  if (settings.frame_qos_depth <= 0) {
    throw std::invalid_argument("frame_qos_depth must be positive");
  }
  if (settings.frame_qos_reliability != "reliable" &&
    settings.frame_qos_reliability != "best_effort")
  {
    throw std::invalid_argument("frame_qos_reliability must be reliable or best_effort");
  }
}

void apply_controlled_delay(const std::int64_t delay_ms, const std::string_view mode)
{
  if (delay_ms < 0) {
    throw std::invalid_argument("delay must be non-negative");
  }
  if (mode != "sleep" && mode != "busy_compute") {
    throw std::invalid_argument("unsupported planner delay mode");
  }
  if (delay_ms == 0) {
    return;
  }

  const auto duration = std::chrono::milliseconds(delay_ms);
  if (mode == "sleep") {
    std::this_thread::sleep_for(duration);
    return;
  }

  const auto deadline = std::chrono::steady_clock::now() + duration;
  while (std::chrono::steady_clock::now() < deadline) {
    std::atomic_signal_fence(std::memory_order_seq_cst);
  }
}

std::string json_escape(const std::string_view value)
{
  std::ostringstream stream;
  for (const unsigned char character : value) {
    switch (character) {
      case '\\': stream << "\\\\"; break;
      case '"': stream << "\\\""; break;
      case '\b': stream << "\\b"; break;
      case '\f': stream << "\\f"; break;
      case '\n': stream << "\\n"; break;
      case '\r': stream << "\\r"; break;
      case '\t': stream << "\\t"; break;
      default:
        if (character < 0x20U) {
          constexpr char digits[] = "0123456789abcdef";
          stream << "\\u00" << digits[(character >> 4U) & 0x0fU]
                 << digits[character & 0x0fU];
        } else {
          stream << static_cast<char>(character);
        }
    }
  }
  return stream.str();
}

}  // namespace vlm_planner_cpp_pkg
