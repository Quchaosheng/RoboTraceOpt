#include <stdexcept>
#include <string>

#include "gtest/gtest.h"
#include "vlm_planner_cpp_pkg/runtime_contract.hpp"

namespace
{

using vlm_planner_cpp_pkg::RuntimeSettings;

TEST(RuntimeContract, ExplicitMockIsTheOnlyMotionBackend)
{
  const auto mock = vlm_planner_cpp_pkg::select_backend("  MOCK ");
  EXPECT_EQ(mock.requested, "mock");
  EXPECT_EQ(mock.active, "mock");
  EXPECT_TRUE(mock.motion_enabled());

  for (const std::string backend : {"llm", "replay", "unknown"}) {
    const auto selection = vlm_planner_cpp_pkg::select_backend(backend);
    EXPECT_EQ(selection.active, "abstain");
    EXPECT_FALSE(selection.motion_enabled());
    EXPECT_FALSE(selection.reason.empty());
  }

  const auto empty = vlm_planner_cpp_pkg::select_backend("  ");
  EXPECT_TRUE(empty.requested.empty());
  EXPECT_EQ(empty.active, "abstain");
  EXPECT_FALSE(empty.motion_enabled());
}

TEST(RuntimeContract, ExecutorThreadBoundsAreEnforced)
{
  RuntimeSettings settings;
  EXPECT_NO_THROW(vlm_planner_cpp_pkg::validate_runtime_settings(settings));
  settings.executor_threads = 4;
  EXPECT_NO_THROW(vlm_planner_cpp_pkg::validate_runtime_settings(settings));
  settings.executor_threads = 0;
  EXPECT_THROW(vlm_planner_cpp_pkg::validate_runtime_settings(settings), std::invalid_argument);
  settings.executor_threads = 5;
  EXPECT_THROW(vlm_planner_cpp_pkg::validate_runtime_settings(settings), std::invalid_argument);
}

TEST(RuntimeContract, DelayAndQosValuesAreValidated)
{
  RuntimeSettings settings;
  settings.planner_delay_mode = "blocking";
  EXPECT_THROW(vlm_planner_cpp_pkg::validate_runtime_settings(settings), std::invalid_argument);
  settings.planner_delay_mode = "sleep";
  settings.frame_qos_depth = 0;
  EXPECT_THROW(vlm_planner_cpp_pkg::validate_runtime_settings(settings), std::invalid_argument);
  settings.frame_qos_depth = 10;
  settings.frame_qos_reliability = "unknown";
  EXPECT_THROW(vlm_planner_cpp_pkg::validate_runtime_settings(settings), std::invalid_argument);
}

TEST(RuntimeContract, TtlMustBePositiveAndZeroContentionLoadIsValid)
{
  RuntimeSettings settings;
  settings.observation_ttl_ms = 1;
  settings.executor_contention_period_ms = 1;
  settings.executor_contention_load_ms = 0;
  EXPECT_NO_THROW(vlm_planner_cpp_pkg::validate_runtime_settings(settings));

  settings.observation_ttl_ms = 0;
  EXPECT_THROW(vlm_planner_cpp_pkg::validate_runtime_settings(settings), std::invalid_argument);
  settings.observation_ttl_ms = 1;
  settings.executor_contention_period_ms = 0;
  EXPECT_THROW(vlm_planner_cpp_pkg::validate_runtime_settings(settings), std::invalid_argument);
  settings.executor_contention_period_ms = 1;
  settings.executor_contention_load_ms = -1;
  EXPECT_THROW(vlm_planner_cpp_pkg::validate_runtime_settings(settings), std::invalid_argument);
}

TEST(RuntimeContract, ControlledDelaySupportsBothModes)
{
  EXPECT_NO_THROW(vlm_planner_cpp_pkg::apply_controlled_delay(0, "sleep"));
  EXPECT_NO_THROW(vlm_planner_cpp_pkg::apply_controlled_delay(0, "busy_compute"));
  EXPECT_THROW(
    vlm_planner_cpp_pkg::apply_controlled_delay(0, "unsupported"), std::invalid_argument);
  EXPECT_THROW(vlm_planner_cpp_pkg::apply_controlled_delay(-1, "sleep"), std::invalid_argument);
}

TEST(RuntimeContract, EventStringsAreJsonEscaped)
{
  EXPECT_EQ(vlm_planner_cpp_pkg::json_escape("a\"b\\c\n"), "a\\\"b\\\\c\\n");
  EXPECT_EQ(vlm_planner_cpp_pkg::json_escape(std::string{"\x01", 1}), "\\u0001");
}

}  // namespace
