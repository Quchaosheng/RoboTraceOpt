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
    llm_api_style = LaunchConfiguration("llm_api_style")
    llm_timeout_s = LaunchConfiguration("llm_timeout_s")
    llm_vision_mode = LaunchConfiguration("llm_vision_mode")
    llm_max_image_bytes = LaunchConfiguration("llm_max_image_bytes")
    observation_ttl_ms = LaunchConfiguration("observation_ttl_ms")
    observation_max_future_skew_ms = LaunchConfiguration("observation_max_future_skew_ms")
    model_queue_delay_ms = LaunchConfiguration("model_queue_delay_ms")
    model_queue_delay_mode = LaunchConfiguration("model_queue_delay_mode")
    model_dedup_window_ms = LaunchConfiguration("model_dedup_window_ms")
    model_failure_window_ms = LaunchConfiguration("model_failure_window_ms")
    model_failure_storm_count = LaunchConfiguration("model_failure_storm_count")
    model_record_path = LaunchConfiguration("model_record_path")
    model_replay_path = LaunchConfiguration("model_replay_path")
    fallback_to_mock = LaunchConfiguration("fallback_to_mock")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "planner_backend",
                default_value="mock",
                description="Planner backend: mock, llm, or replay.",
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
                "llm_api_style",
                default_value=os.environ.get("LLM_API_STYLE", "chat_completions"),
                description="OpenAI-compatible API style: chat_completions or responses.",
            ),
            DeclareLaunchArgument(
                "llm_timeout_s",
                default_value="3.0",
                description="LLM request timeout in seconds.",
            ),
            DeclareLaunchArgument(
                "llm_vision_mode",
                default_value="metadata",
                description="LLM input mode: metadata or payload_base64.",
            ),
            DeclareLaunchArgument(
                "llm_max_image_bytes",
                default_value="1000000",
                description="Maximum image payload size forwarded to the LLM.",
            ),
            DeclareLaunchArgument(
                "observation_ttl_ms",
                default_value="1000",
                description="Maximum camera-observation age allowed through planner publication.",
            ),
            DeclareLaunchArgument(
                "observation_max_future_skew_ms",
                default_value="100",
                description="Maximum allowed future timestamp skew for a camera observation.",
            ),
            DeclareLaunchArgument(
                "model_queue_delay_ms",
                default_value="0",
                description="Deterministic pre-inference queue delay for F7-style experiments.",
            ),
            DeclareLaunchArgument(
                "model_queue_delay_mode",
                default_value="sleep",
                description="F7 queue delay mechanism: sleep or busy_compute.",
            ),
            DeclareLaunchArgument(
                "model_dedup_window_ms",
                default_value="10000",
                description="Trace/sequence request deduplication window.",
            ),
            DeclareLaunchArgument(
                "model_failure_window_ms",
                default_value="30000",
                description="Rolling window for F10-style model failure detection.",
            ),
            DeclareLaunchArgument(
                "model_failure_storm_count",
                default_value="3",
                description="Failure count that emits a model fallback-storm event.",
            ),
            DeclareLaunchArgument(
                "model_record_path",
                default_value="",
                description="Optional JSONL path for secret-safe normalized model decision records.",
            ),
            DeclareLaunchArgument(
                "model_replay_path",
                default_value="",
                description="Required normalized decision recording when planner_backend is replay.",
            ),
            DeclareLaunchArgument(
                "fallback_to_mock",
                default_value="false",
                description=(
                    "Deprecated compatibility flag. LLM failures always abstain; use "
                    "planner_backend:=mock only for explicit mock motion."
                ),
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
                        "llm_api_style": ParameterValue(
                            llm_api_style, value_type=str
                        ),
                        "llm_timeout_s": ParameterValue(
                            llm_timeout_s, value_type=float
                        ),
                        "llm_vision_mode": ParameterValue(
                            llm_vision_mode, value_type=str
                        ),
                        "llm_max_image_bytes": ParameterValue(
                            llm_max_image_bytes, value_type=int
                        ),
                        "observation_ttl_ms": ParameterValue(
                            observation_ttl_ms, value_type=int
                        ),
                        "observation_max_future_skew_ms": ParameterValue(
                            observation_max_future_skew_ms, value_type=int
                        ),
                        "model_queue_delay_ms": ParameterValue(
                            model_queue_delay_ms, value_type=int
                        ),
                        "model_queue_delay_mode": ParameterValue(
                            model_queue_delay_mode, value_type=str
                        ),
                        "model_dedup_window_ms": ParameterValue(
                            model_dedup_window_ms, value_type=int
                        ),
                        "model_failure_window_ms": ParameterValue(
                            model_failure_window_ms, value_type=int
                        ),
                        "model_failure_storm_count": ParameterValue(
                            model_failure_storm_count, value_type=int
                        ),
                        "model_record_path": ParameterValue(
                            model_record_path, value_type=str
                        ),
                        "model_replay_path": ParameterValue(
                            model_replay_path, value_type=str
                        ),
                        "fallback_to_mock": ParameterValue(
                            fallback_to_mock, value_type=bool
                        ),
                    },
                ],
            ),
        ]
    )
