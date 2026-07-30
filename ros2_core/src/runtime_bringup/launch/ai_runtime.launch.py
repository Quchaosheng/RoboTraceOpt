import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.conditions import IfCondition
from launch.actions import DeclareLaunchArgument
from launch.substitutions import PythonExpression
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def package_config(package_name, config_file_name):
    return os.path.join(
        get_package_share_directory(package_name),
        "config",
        config_file_name,
    )


def generate_launch_description():
    camera_rate_hz = LaunchConfiguration("camera_rate_hz")
    frame_payload_bytes = LaunchConfiguration("frame_payload_bytes")
    camera_image_file = LaunchConfiguration("camera_image_file")
    camera_encoding = LaunchConfiguration("camera_encoding")
    camera_width = LaunchConfiguration("camera_width")
    camera_height = LaunchConfiguration("camera_height")
    camera_fixed_trace_id = LaunchConfiguration("camera_fixed_trace_id")
    camera_fixed_oracle_id = LaunchConfiguration("camera_fixed_oracle_id")
    camera_fixed_sequence_id = LaunchConfiguration("camera_fixed_sequence_id")
    frame_qos_depth = LaunchConfiguration("frame_qos_depth")
    frame_qos_reliability = LaunchConfiguration("frame_qos_reliability")
    input_rate_hz = LaunchConfiguration("input_rate_hz")
    second_camera_enabled = LaunchConfiguration("second_camera_enabled")
    profile = LaunchConfiguration("profile")
    planner_backend = LaunchConfiguration("planner_backend")
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
    planner_delay_ms = LaunchConfiguration("planner_delay_ms")
    planner_delay_mode = LaunchConfiguration("planner_delay_mode")
    executor_contention_enabled = LaunchConfiguration("executor_contention_enabled")
    executor_contention_period_ms = LaunchConfiguration("executor_contention_period_ms")
    executor_contention_load_ms = LaunchConfiguration("executor_contention_load_ms")
    executor_threads = LaunchConfiguration("executor_threads")
    action_delay_ms = LaunchConfiguration("action_delay_ms")
    action_manager_enabled = LaunchConfiguration("action_manager_enabled")
    action_feedback_period_ms = LaunchConfiguration("action_feedback_period_ms")
    action_goal_timeout_ms = LaunchConfiguration("action_goal_timeout_ms")
    control_delay_ms = LaunchConfiguration("control_delay_ms")
    can_interface = LaunchConfiguration("can_interface")
    can_send_delay_ms = LaunchConfiguration("can_send_delay_ms")
    command_ttl_ms = LaunchConfiguration("command_ttl_ms")
    command_max_future_skew_ms = LaunchConfiguration("command_max_future_skew_ms")
    command_dedup_window_ms = LaunchConfiguration("command_dedup_window_ms")
    max_command_speed = LaunchConfiguration("max_command_speed")
    ack_enabled = LaunchConfiguration("ack_enabled")
    ack_mode = LaunchConfiguration("ack_mode")
    ack_timeout_ms = LaunchConfiguration("ack_timeout_ms")
    max_retries = LaunchConfiguration("max_retries")
    retry_backoff_ms = LaunchConfiguration("retry_backoff_ms")
    mock_ack_delay_ms = LaunchConfiguration("mock_ack_delay_ms")
    mock_ack_policy = LaunchConfiguration("mock_ack_policy")
    ack_can_id_offset = LaunchConfiguration("ack_can_id_offset")
    runtime_event_enabled = LaunchConfiguration("runtime_event_enabled")
    probe_enabled = LaunchConfiguration("probe_enabled")
    output_path = LaunchConfiguration("output_path")
    probe_output_path = LaunchConfiguration("probe_output_path")
    mock_mode = LaunchConfiguration("mock_mode")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "profile",
                default_value="enhanced",
                description="Runtime profile: baseline or enhanced.",
            ),
            DeclareLaunchArgument(
                "camera_rate_hz",
                default_value="1.0",
                description="Camera mock publish rate in Hz.",
            ),
            DeclareLaunchArgument(
                "frame_payload_bytes",
                default_value="0",
                description="Camera frame transport payload size in bytes.",
            ),
            DeclareLaunchArgument(
                "frame_qos_depth",
                default_value="10",
                description="History depth for the /camera/frame endpoints.",
            ),
            DeclareLaunchArgument(
                "frame_qos_reliability",
                default_value="reliable",
                description="Reliability for /camera/frame: reliable or best_effort.",
            ),
            DeclareLaunchArgument(
                "input_rate_hz",
                default_value="1.0",
                description="Baseline input publish rate in Hz.",
            ),
            DeclareLaunchArgument(
                "second_camera_enabled",
                default_value="false",
                description=(
                    "Start a second camera_mock_node publishing to the same /camera/frame topic. "
                    "This is useful for sequence_id collision experiments."
                ),
            ),
            DeclareLaunchArgument(
                "planner_backend",
                default_value="mock",
                description="VLM planner backend: mock, llm, or replay.",
            ),
            DeclareLaunchArgument(
                "camera_image_file",
                default_value="",
                description="Optional fixed image file published as CameraFrame payload.",
            ),
            DeclareLaunchArgument("camera_encoding", default_value="mock"),
            DeclareLaunchArgument("camera_width", default_value="640"),
            DeclareLaunchArgument("camera_height", default_value="480"),
            DeclareLaunchArgument(
                "camera_fixed_trace_id",
                default_value="",
                description="Fault-injection-only fixed trace identity for duplicate-request checks.",
            ),
            DeclareLaunchArgument(
                "camera_fixed_oracle_id",
                default_value="",
                description="Fault-injection-only fixed oracle identity for duplicate-request checks.",
            ),
            DeclareLaunchArgument(
                "camera_fixed_sequence_id",
                default_value="0",
                description="Fault-injection-only fixed sequence identity; zero keeps normal sequencing.",
            ),
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
                description="Environment variable containing the LLM API key.",
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
            DeclareLaunchArgument(
                "planner_delay_ms",
                default_value="50",
                description="Mock planner processing delay in milliseconds.",
            ),
            DeclareLaunchArgument(
                "planner_delay_mode",
                default_value="sleep",
                description="Enhanced planner delay mechanism: sleep or busy_compute.",
            ),
            DeclareLaunchArgument(
                "executor_contention_enabled",
                default_value="false",
                description="Enable the controlled single-executor contention timer.",
            ),
            DeclareLaunchArgument(
                "executor_contention_period_ms",
                default_value="25",
                description="Contention timer period in milliseconds.",
            ),
            DeclareLaunchArgument(
                "executor_contention_load_ms",
                default_value="0",
                description="Busy-compute load per contention callback in milliseconds.",
            ),
            DeclareLaunchArgument(
                "executor_threads",
                default_value="1",
                description="Planner executor thread count from 1 to 4.",
            ),
            DeclareLaunchArgument(
                "action_delay_ms",
                default_value="100",
                description="Mock robot action execution delay in milliseconds.",
            ),
            DeclareLaunchArgument(
                "action_manager_enabled",
                default_value="false",
                description=(
                    "Use a serial AI-Planner -> ActionManager -> CANBridge chain instead of "
                    "parallel planner-to-action and planner-to-CAN branches."
                ),
            ),
            DeclareLaunchArgument(
                "action_feedback_period_ms",
                default_value="50",
                description="ActionManager feedback period in milliseconds.",
            ),
            DeclareLaunchArgument(
                "action_goal_timeout_ms",
                default_value="0",
                description="ActionManager goal timeout in milliseconds; 0 disables timeout.",
            ),
            DeclareLaunchArgument(
                "control_delay_ms",
                default_value="20",
                description="Baseline control execution delay in milliseconds.",
            ),
            DeclareLaunchArgument(
                "can_interface",
                default_value="vcan0",
                description="SocketCAN interface used by can_bridge_node, for example vcan0 or can0.",
            ),
            DeclareLaunchArgument(
                "can_send_delay_ms",
                default_value="5",
                description="Mock CAN send delay in milliseconds.",
            ),
            DeclareLaunchArgument(
                "command_ttl_ms",
                default_value="1000",
                description="Maximum planner-command age permitted at the CAN execution boundary.",
            ),
            DeclareLaunchArgument(
                "command_max_future_skew_ms",
                default_value="100",
                description="Maximum allowed future monotonic-clock skew for a CAN command.",
            ),
            DeclareLaunchArgument(
                "command_dedup_window_ms",
                default_value="10000",
                description="CAN request identity deduplication window in milliseconds.",
            ),
            DeclareLaunchArgument(
                "max_command_speed",
                default_value="1.0",
                description="Maximum finite normalized speed admitted to CAN execution.",
            ),
            DeclareLaunchArgument(
                "ack_enabled",
                default_value="true",
                description="Enable CAN ACK RuntimeEvent closure in can_bridge_node.",
            ),
            DeclareLaunchArgument(
                "ack_mode",
                default_value="mock",
                description="CAN ACK source: mock, socketcan, or disabled.",
            ),
            DeclareLaunchArgument(
                "ack_timeout_ms",
                default_value="50",
                description="ACK timeout budget in milliseconds.",
            ),
            DeclareLaunchArgument(
                "max_retries",
                default_value="2",
                description="Maximum ACK retry attempts.",
            ),
            DeclareLaunchArgument(
                "retry_backoff_ms",
                default_value="10",
                description="Backoff before retrying CAN send after ACK timeout.",
            ),
            DeclareLaunchArgument(
                "mock_ack_delay_ms",
                default_value="5",
                description="Mock ACK delay in milliseconds.",
            ),
            DeclareLaunchArgument(
                "mock_ack_policy",
                default_value="success",
                description="Mock ACK policy: success, delayed, drop_first, or drop.",
            ),
            DeclareLaunchArgument(
                "ack_can_id_offset",
                default_value="128",
                description="CAN ID offset used to match ACK frames.",
            ),
            DeclareLaunchArgument(
                "runtime_event_enabled",
                default_value="true",
                description=(
                    "Enable RuntimeEvent instrumentation in camera/planner/action/can nodes "
                    "and start runtime_event_logger_node."
                ),
            ),
            DeclareLaunchArgument(
                "output_path",
                default_value="logs/runtime_events.jsonl",
                description="RuntimeEvent JSONL output path.",
            ),
            DeclareLaunchArgument(
                "probe_enabled",
                default_value="false",
                description="Enable independent probe latency collection for overhead experiments.",
            ),
            DeclareLaunchArgument(
                "probe_output_path",
                default_value="logs/probe_latency.csv",
                description="Latency probe CSV output path.",
            ),
            DeclareLaunchArgument(
                "mock_mode",
                default_value="true",
                description="Run CAN bridge without requiring a real SocketCAN interface.",
            ),
            Node(
                package="minimal_runtime_demo",
                executable="input_node",
                name="input_node",
                output="screen",
                condition=IfCondition(
                    PythonExpression(["'", profile, "' == 'baseline'"])
                ),
                parameters=[
                    package_config("minimal_runtime_demo", "demo.yaml"),
                    {
                        "input_rate_hz": ParameterValue(
                            input_rate_hz, value_type=float
                        ),
                    },
                ],
            ),
            Node(
                package="minimal_runtime_demo",
                executable="planner_node",
                name="planner_node",
                output="screen",
                condition=IfCondition(
                    PythonExpression(["'", profile, "' == 'baseline'"])
                ),
                parameters=[
                    package_config("minimal_runtime_demo", "demo.yaml"),
                    {
                        "planner_delay_ms": ParameterValue(
                            planner_delay_ms, value_type=int
                        ),
                    },
                ],
            ),
            Node(
                package="minimal_runtime_demo",
                executable="action_node",
                name="action_node",
                output="screen",
                condition=IfCondition(
                    PythonExpression(["'", profile, "' == 'baseline'"])
                ),
                parameters=[
                    package_config("minimal_runtime_demo", "demo.yaml"),
                    {
                        "action_delay_ms": ParameterValue(
                            action_delay_ms, value_type=int
                        ),
                    },
                ],
            ),
            Node(
                package="minimal_runtime_demo",
                executable="control_node",
                name="control_node",
                output="screen",
                condition=IfCondition(
                    PythonExpression(["'", profile, "' == 'baseline'"])
                ),
                parameters=[
                    package_config("minimal_runtime_demo", "demo.yaml"),
                    {
                        "control_delay_ms": ParameterValue(
                            control_delay_ms, value_type=int
                        ),
                    },
                ],
            ),
            Node(
                package="camera_mock_pkg",
                executable="camera_mock_node",
                name="camera_mock_node",
                output="screen",
                condition=IfCondition(
                    PythonExpression(["'", profile, "' == 'enhanced'"])
                ),
                parameters=[
                    package_config("camera_mock_pkg", "camera_mock.yaml"),
                    {
                        "camera_rate_hz": ParameterValue(
                            camera_rate_hz, value_type=float
                        ),
                        "frame_payload_bytes": ParameterValue(
                            frame_payload_bytes, value_type=int
                        ),
                        "image_file": ParameterValue(camera_image_file, value_type=str),
                        "encoding": ParameterValue(camera_encoding, value_type=str),
                        "width": ParameterValue(camera_width, value_type=int),
                        "height": ParameterValue(camera_height, value_type=int),
                        "fixed_trace_id": ParameterValue(
                            camera_fixed_trace_id, value_type=str
                        ),
                        "fixed_oracle_id": ParameterValue(
                            camera_fixed_oracle_id, value_type=str
                        ),
                        "fixed_sequence_id": ParameterValue(
                            camera_fixed_sequence_id, value_type=int
                        ),
                        "frame_qos_depth": ParameterValue(
                            frame_qos_depth, value_type=int
                        ),
                        "frame_qos_reliability": ParameterValue(
                            frame_qos_reliability, value_type=str
                        ),
                        "runtime_event_enabled": ParameterValue(
                            runtime_event_enabled, value_type=bool
                        ),
                    },
                ],
            ),
            Node(
                package="camera_mock_pkg",
                executable="camera_mock_node",
                name="camera_mock_node_secondary",
                output="screen",
                condition=IfCondition(
                    PythonExpression(
                        [
                            "'",
                            profile,
                            "' == 'enhanced' and '",
                            second_camera_enabled,
                            "' == 'true'",
                        ]
                    )
                ),
                parameters=[
                    package_config("camera_mock_pkg", "camera_mock.yaml"),
                    {
                        "camera_rate_hz": ParameterValue(
                            camera_rate_hz, value_type=float
                        ),
                        "frame_payload_bytes": ParameterValue(
                            frame_payload_bytes, value_type=int
                        ),
                        "image_file": ParameterValue(camera_image_file, value_type=str),
                        "encoding": ParameterValue(camera_encoding, value_type=str),
                        "width": ParameterValue(camera_width, value_type=int),
                        "height": ParameterValue(camera_height, value_type=int),
                        "fixed_trace_id": ParameterValue(
                            camera_fixed_trace_id, value_type=str
                        ),
                        "fixed_oracle_id": ParameterValue(
                            camera_fixed_oracle_id, value_type=str
                        ),
                        "fixed_sequence_id": ParameterValue(
                            camera_fixed_sequence_id, value_type=int
                        ),
                        "frame_qos_depth": ParameterValue(
                            frame_qos_depth, value_type=int
                        ),
                        "frame_qos_reliability": ParameterValue(
                            frame_qos_reliability, value_type=str
                        ),
                        "runtime_event_enabled": ParameterValue(
                            runtime_event_enabled, value_type=bool
                        ),
                    },
                ],
            ),
            Node(
                package="vlm_planner_pkg",
                executable="vlm_planner_node",
                name="vlm_planner_node",
                output="screen",
                condition=IfCondition(
                    PythonExpression(["'", profile, "' == 'enhanced'"])
                ),
                parameters=[
                    package_config("vlm_planner_pkg", "planner.yaml"),
                    {
                        "planner_backend": ParameterValue(
                            planner_backend, value_type=str
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
                        "planner_delay_ms": ParameterValue(
                            planner_delay_ms, value_type=int
                        ),
                        "planner_delay_mode": ParameterValue(
                            planner_delay_mode, value_type=str
                        ),
                        "frame_qos_depth": ParameterValue(
                            frame_qos_depth, value_type=int
                        ),
                        "frame_qos_reliability": ParameterValue(
                            frame_qos_reliability, value_type=str
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
                        "runtime_event_enabled": ParameterValue(
                            runtime_event_enabled, value_type=bool
                        ),
                    },
                ],
            ),
            Node(
                package="robot_action_pkg",
                executable="robot_action_node",
                name="robot_action_node",
                output="screen",
                condition=IfCondition(
                    PythonExpression(
                        [
                            "'",
                            profile,
                            "' == 'enhanced' and '",
                            action_manager_enabled,
                            "' != 'true'",
                        ]
                    )
                ),
                parameters=[
                    package_config("robot_action_pkg", "robot_action.yaml"),
                    {
                        "action_delay_ms": ParameterValue(
                            action_delay_ms, value_type=int
                        ),
                        "runtime_event_enabled": ParameterValue(
                            runtime_event_enabled, value_type=bool
                        ),
                    },
                ],
            ),
            Node(
                package="robot_action_pkg",
                executable="action_manager_node",
                name="action_manager_node",
                output="screen",
                condition=IfCondition(
                    PythonExpression(
                        [
                            "'",
                            profile,
                            "' == 'enhanced' and '",
                            action_manager_enabled,
                            "' == 'true'",
                        ]
                    )
                ),
                parameters=[
                    package_config("robot_action_pkg", "robot_action.yaml"),
                    {
                        "command_topic": "/planner/command",
                        "result_topic": "/action_manager/command_result",
                        "action_name": "/robot_command",
                        "action_delay_ms": ParameterValue(
                            action_delay_ms, value_type=int
                        ),
                        "feedback_period_ms": ParameterValue(
                            action_feedback_period_ms, value_type=int
                        ),
                        "goal_timeout_ms": ParameterValue(
                            action_goal_timeout_ms, value_type=int
                        ),
                        "runtime_event_enabled": ParameterValue(
                            runtime_event_enabled, value_type=bool
                        ),
                    },
                ],
            ),
            Node(
                package="can_bridge_pkg",
                executable="can_bridge_node",
                name="can_bridge_node",
                output="screen",
                condition=IfCondition(
                    PythonExpression(["'", profile, "' == 'enhanced'"])
                ),
                parameters=[
                    package_config("can_bridge_pkg", "can_bridge.yaml"),
                    {
                        "command_topic": ParameterValue(
                            PythonExpression(
                                [
                                    "'/action_manager/command_result' if '",
                                    action_manager_enabled,
                                    "' == 'true' else '/planner/command'",
                                ]
                            ),
                            value_type=str,
                        ),
                        "can_interface": ParameterValue(can_interface, value_type=str),
                        "can_send_delay_ms": ParameterValue(
                            can_send_delay_ms, value_type=int
                        ),
                        "command_ttl_ms": ParameterValue(
                            command_ttl_ms, value_type=int
                        ),
                        "command_max_future_skew_ms": ParameterValue(
                            command_max_future_skew_ms, value_type=int
                        ),
                        "command_dedup_window_ms": ParameterValue(
                            command_dedup_window_ms, value_type=int
                        ),
                        "max_command_speed": ParameterValue(
                            max_command_speed, value_type=float
                        ),
                        "mock_mode": ParameterValue(mock_mode, value_type=bool),
                        "ack_enabled": ParameterValue(ack_enabled, value_type=bool),
                        "ack_mode": ParameterValue(ack_mode, value_type=str),
                        "ack_timeout_ms": ParameterValue(
                            ack_timeout_ms, value_type=int
                        ),
                        "max_retries": ParameterValue(max_retries, value_type=int),
                        "retry_backoff_ms": ParameterValue(
                            retry_backoff_ms, value_type=int
                        ),
                        "mock_ack_delay_ms": ParameterValue(
                            mock_ack_delay_ms, value_type=int
                        ),
                        "mock_ack_policy": ParameterValue(
                            mock_ack_policy, value_type=str
                        ),
                        "ack_can_id_offset": ParameterValue(
                            ack_can_id_offset, value_type=int
                        ),
                        "runtime_event_enabled": ParameterValue(
                            runtime_event_enabled, value_type=bool
                        ),
                        "probe_enabled": ParameterValue(probe_enabled, value_type=bool),
                    },
                ],
            ),
            Node(
                package="runtime_logger_pkg",
                executable="latency_probe_node",
                name="latency_probe_node",
                output="screen",
                condition=IfCondition(probe_enabled),
                parameters=[
                    {
                        "input_topic": ParameterValue(
                            PythonExpression(
                                [
                                    "'/action_manager/command_result' if '",
                                    action_manager_enabled,
                                    "' == 'true' else '/planner/command'",
                                ]
                            ),
                            value_type=str,
                        ),
                        "output_path": ParameterValue(
                            probe_output_path, value_type=str
                        ),
                        "flush_every_sample": True,
                    },
                ],
            ),
            Node(
                package="runtime_logger_pkg",
                executable="runtime_event_logger_node",
                name="runtime_event_logger_node",
                output="screen",
                condition=IfCondition(runtime_event_enabled),
                parameters=[
                    package_config("runtime_logger_pkg", "runtime_logger.yaml"),
                    {
                        "output_path": ParameterValue(output_path, value_type=str),
                        "flush_every_event": True,
                    },
                ],
            ),
        ]
    )
