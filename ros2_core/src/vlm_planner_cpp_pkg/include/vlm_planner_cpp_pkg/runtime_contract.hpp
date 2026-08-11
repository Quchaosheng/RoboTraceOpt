#pragma once

#include <cstdint>
#include <string>
#include <string_view>

namespace vlm_planner_cpp_pkg
{

struct BackendSelection
{
  std::string requested;
  std::string active;
  std::string reason;

  [[nodiscard]] bool motion_enabled() const noexcept {return active == "mock";}
};

struct RuntimeSettings
{
  std::int64_t planner_delay_ms{50};
  std::string planner_delay_mode{"sleep"};
  std::int64_t model_queue_delay_ms{0};
  std::string model_queue_delay_mode{"sleep"};
  std::int64_t executor_contention_period_ms{25};
  std::int64_t executor_contention_load_ms{0};
  std::int64_t executor_threads{1};
  std::int64_t frame_qos_depth{10};
  std::string frame_qos_reliability{"reliable"};
  std::int64_t observation_ttl_ms{1000};
};

[[nodiscard]] BackendSelection select_backend(std::string requested);
void validate_runtime_settings(const RuntimeSettings & settings);
void apply_controlled_delay(std::int64_t delay_ms, std::string_view mode);
[[nodiscard]] std::string json_escape(std::string_view value);

}  // namespace vlm_planner_cpp_pkg
