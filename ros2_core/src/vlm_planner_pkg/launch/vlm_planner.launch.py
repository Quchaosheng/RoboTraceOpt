import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    config_file = os.path.join(
        get_package_share_directory("vlm_planner_pkg"),
        "config",
        "planner.yaml",
    )

    planner_backend = LaunchConfiguration("planner_backend")
    planner_delay_ms = LaunchConfiguration("planner_delay_ms")
    planner_delay_mode = LaunchConfiguration("planner_delay_mode")
    executor_contention_enabled = LaunchConfiguration("executor_contention_enabled")
    executor_contention_period_ms = LaunchConfiguration("executor_contention_period_ms")
    executor_contention_load_ms = LaunchConfiguration("executor_contention_load_ms")
    executor_threads = LaunchConfiguration("executor_threads")
    llm_provider = LaunchConfiguration("llm_provider")
    llm_api_base = LaunchConfiguration("llm_api_base")
    llm_api_key_env = LaunchConfiguration("llm_api_key_env")
    llm_model = LaunchConfiguration("llm_model")
    llm_timeout_s = LaunchConfiguration("llm_timeout_s")
    fallback_to_mock = LaunchConfiguration("fallback_to_mock")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "planner_backend",
                default_value="mock",
                description="Planner backend: mock or llm.",
            ),
            DeclareLaunchArgument(
                "planner_delay_ms",
                default_value="50",
                description="Mock planner delay in milliseconds.",
            ),
            DeclareLaunchArgument(
                "planner_delay_mode",
                default_value="sleep",
                description="Mock planner delay mechanism: sleep or busy_compute.",
            ),
            DeclareLaunchArgument("executor_contention_enabled", default_value="false"),
            DeclareLaunchArgument("executor_contention_period_ms", default_value="25"),
            DeclareLaunchArgument("executor_contention_load_ms", default_value="0"),
            DeclareLaunchArgument("executor_threads", default_value="1"),
            DeclareLaunchArgument(
                "llm_provider",
                default_value="openai_compatible",
                description="LLM provider adapter name.",
            ),
            DeclareLaunchArgument(
                "llm_api_base",
                default_value=os.environ.get("LLM_API_BASE", ""),
                description="OpenAI-compatible API base URL.",
            ),
            DeclareLaunchArgument(
                "llm_api_key_env",
                default_value="LLM_API_KEY",
                description="Environment variable that contains the LLM API key.",
            ),
            DeclareLaunchArgument(
                "llm_model",
                default_value=os.environ.get("LLM_MODEL", ""),
                description="LLM model name.",
            ),
            DeclareLaunchArgument(
                "llm_timeout_s",
                default_value="3.0",
                description="LLM request timeout in seconds.",
            ),
            DeclareLaunchArgument(
                "fallback_to_mock",
                default_value="true",
                description="Fallback to mock planner when LLM backend is unavailable.",
            ),
            Node(
                package="vlm_planner_pkg",
                executable="vlm_planner_node",
                name="vlm_planner_node",
                output="screen",
                parameters=[
                    config_file,
                    {
                        "planner_backend": ParameterValue(
                            planner_backend, value_type=str
                        ),
                        "planner_delay_ms": ParameterValue(
                            planner_delay_ms, value_type=int
                        ),
                        "planner_delay_mode": ParameterValue(
                            planner_delay_mode, value_type=str
                        ),
                        "executor_contention_enabled": ParameterValue(
                            executor_contention_enabled, value_type=bool
                        ),
                        "executor_contention_period_ms": ParameterValue(
                            executor_contention_period_ms, value_type=int
                        ),
                        "executor_contention_load_ms": ParameterValue(
                            executor_contention_load_ms, value_type=int
                        ),
                        "executor_threads": ParameterValue(
                            executor_threads, value_type=int
                        ),
                        "llm_provider": ParameterValue(llm_provider, value_type=str),
                        "llm_api_base": ParameterValue(llm_api_base, value_type=str),
                        "llm_api_key_env": ParameterValue(
                            llm_api_key_env, value_type=str
                        ),
                        "llm_model": ParameterValue(llm_model, value_type=str),
                        "llm_timeout_s": ParameterValue(
                            llm_timeout_s, value_type=float
                        ),
                        "fallback_to_mock": ParameterValue(
                            fallback_to_mock, value_type=bool
                        ),
                    },
                ],
            ),
        ]
    )
