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
    frame_qos_depth = LaunchConfiguration("frame_qos_depth")
    frame_qos_reliability = LaunchConfiguration("frame_qos_reliability")
    input_rate_hz = LaunchConfiguration("input_rate_hz")
    second_camera_enabled = LaunchConfiguration("second_camera_enabled")
    profile = LaunchConfiguration("profile")
    planner_backend = LaunchConfiguration("planner_backend")
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
    ack_enabled = LaunchConfiguration("ack_enabled")
    ack_mode = LaunchConfiguration("ack_mode")
    ack_timeout_ms = LaunchConfiguration("ack_timeout_ms")
    max_retries = LaunchConfiguration("max_retries")
    retry_backoff_ms = LaunchConfiguration("retry_backoff_ms")
    mock_ack_delay_ms = LaunchConfiguration("mock_ack_delay_ms")
    mock_ack_policy = LaunchConfiguration("mock_ack_policy")
    runtime_event_enabled = LaunchConfiguration("runtime_event_enabled")
    probe_enabled = LaunchConfiguration("probe_enabled")
    output_path = LaunchConfiguration("output_path")
    probe_output_path = LaunchConfiguration("probe_output_path")
    mock_mode = LaunchConfiguration("mock_mode")

    return LaunchDescription([
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
            description="VLM planner backend: mock or llm.",
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
            condition=IfCondition(PythonExpression(["'", profile, "' == 'baseline'"])),
            parameters=[
                package_config("minimal_runtime_demo", "demo.yaml"),
                {
                    "input_rate_hz": ParameterValue(input_rate_hz, value_type=float),
                },
            ],
        ),
        Node(
            package="minimal_runtime_demo",
            executable="planner_node",
            name="planner_node",
            output="screen",
            condition=IfCondition(PythonExpression(["'", profile, "' == 'baseline'"])),
            parameters=[
                package_config("minimal_runtime_demo", "demo.yaml"),
                {
                    "planner_delay_ms": ParameterValue(planner_delay_ms, value_type=int),
                },
            ],
        ),
        Node(
            package="minimal_runtime_demo",
            executable="action_node",
            name="action_node",
            output="screen",
            condition=IfCondition(PythonExpression(["'", profile, "' == 'baseline'"])),
            parameters=[
                package_config("minimal_runtime_demo", "demo.yaml"),
                {
                    "action_delay_ms": ParameterValue(action_delay_ms, value_type=int),
                },
            ],
        ),
        Node(
            package="minimal_runtime_demo",
            executable="control_node",
            name="control_node",
            output="screen",
            condition=IfCondition(PythonExpression(["'", profile, "' == 'baseline'"])),
            parameters=[
                package_config("minimal_runtime_demo", "demo.yaml"),
                {
                    "control_delay_ms": ParameterValue(control_delay_ms, value_type=int),
                },
            ],
        ),
        Node(
            package="camera_mock_pkg",
            executable="camera_mock_node",
            name="camera_mock_node",
            output="screen",
            condition=IfCondition(PythonExpression(["'", profile, "' == 'enhanced'"])),
            parameters=[
                package_config("camera_mock_pkg", "camera_mock.yaml"),
                {
                    "camera_rate_hz": ParameterValue(camera_rate_hz, value_type=float),
                    "frame_payload_bytes": ParameterValue(frame_payload_bytes, value_type=int),
                    "frame_qos_depth": ParameterValue(frame_qos_depth, value_type=int),
                    "frame_qos_reliability": ParameterValue(
                        frame_qos_reliability, value_type=str
                    ),
                    "runtime_event_enabled": ParameterValue(runtime_event_enabled, value_type=bool),
                },
            ],
        ),
        Node(
            package="camera_mock_pkg",
            executable="camera_mock_node",
            name="camera_mock_node_secondary",
            output="screen",
            condition=IfCondition(
                PythonExpression([
                    "'", profile, "' == 'enhanced' and '",
                    second_camera_enabled,
                    "' == 'true'",
                ])
            ),
            parameters=[
                package_config("camera_mock_pkg", "camera_mock.yaml"),
                {
                    "camera_rate_hz": ParameterValue(camera_rate_hz, value_type=float),
                    "frame_payload_bytes": ParameterValue(frame_payload_bytes, value_type=int),
                    "frame_qos_depth": ParameterValue(frame_qos_depth, value_type=int),
                    "frame_qos_reliability": ParameterValue(
                        frame_qos_reliability, value_type=str
                    ),
                    "runtime_event_enabled": ParameterValue(runtime_event_enabled, value_type=bool),
                },
            ],
        ),
        Node(
            package="vlm_planner_pkg",
            executable="vlm_planner_node",
            name="vlm_planner_node",
            output="screen",
            condition=IfCondition(PythonExpression(["'", profile, "' == 'enhanced'"])),
            parameters=[
                package_config("vlm_planner_pkg", "planner.yaml"),
                {
                    "planner_backend": ParameterValue(planner_backend, value_type=str),
                    "planner_delay_ms": ParameterValue(planner_delay_ms, value_type=int),
                    "planner_delay_mode": ParameterValue(planner_delay_mode, value_type=str),
                    "frame_qos_depth": ParameterValue(frame_qos_depth, value_type=int),
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
                    "executor_threads": ParameterValue(executor_threads, value_type=int),
                    "runtime_event_enabled": ParameterValue(runtime_event_enabled, value_type=bool),
                },
            ],
        ),
        Node(
            package="robot_action_pkg",
            executable="robot_action_node",
            name="robot_action_node",
            output="screen",
            condition=IfCondition(
                PythonExpression([
                    "'", profile, "' == 'enhanced' and '",
                    action_manager_enabled,
                    "' != 'true'",
                ])
            ),
            parameters=[
                package_config("robot_action_pkg", "robot_action.yaml"),
                {
                    "action_delay_ms": ParameterValue(action_delay_ms, value_type=int),
                    "runtime_event_enabled": ParameterValue(runtime_event_enabled, value_type=bool),
                },
            ],
        ),
        Node(
            package="robot_action_pkg",
            executable="action_manager_node",
            name="action_manager_node",
            output="screen",
            condition=IfCondition(
                PythonExpression([
                    "'", profile, "' == 'enhanced' and '",
                    action_manager_enabled,
                    "' == 'true'",
                ])
            ),
            parameters=[
                package_config("robot_action_pkg", "robot_action.yaml"),
                {
                    "command_topic": "/planner/command",
                    "result_topic": "/action_manager/command_result",
                    "action_name": "/robot_command",
                    "action_delay_ms": ParameterValue(action_delay_ms, value_type=int),
                    "feedback_period_ms": ParameterValue(action_feedback_period_ms, value_type=int),
                    "goal_timeout_ms": ParameterValue(action_goal_timeout_ms, value_type=int),
                    "runtime_event_enabled": ParameterValue(runtime_event_enabled, value_type=bool),
                },
            ],
        ),
        Node(
            package="can_bridge_pkg",
            executable="can_bridge_node",
            name="can_bridge_node",
            output="screen",
            condition=IfCondition(PythonExpression(["'", profile, "' == 'enhanced'"])),
            parameters=[
                package_config("can_bridge_pkg", "can_bridge.yaml"),
                {
                    "command_topic": ParameterValue(
                        PythonExpression([
                            "'/action_manager/command_result' if '",
                            action_manager_enabled,
                            "' == 'true' else '/planner/command'",
                        ]),
                        value_type=str,
                    ),
                    "can_interface": ParameterValue(can_interface, value_type=str),
                    "can_send_delay_ms": ParameterValue(can_send_delay_ms, value_type=int),
                    "mock_mode": ParameterValue(mock_mode, value_type=bool),
                    "ack_enabled": ParameterValue(ack_enabled, value_type=bool),
                    "ack_mode": ParameterValue(ack_mode, value_type=str),
                    "ack_timeout_ms": ParameterValue(ack_timeout_ms, value_type=int),
                    "max_retries": ParameterValue(max_retries, value_type=int),
                    "retry_backoff_ms": ParameterValue(retry_backoff_ms, value_type=int),
                    "mock_ack_delay_ms": ParameterValue(mock_ack_delay_ms, value_type=int),
                    "mock_ack_policy": ParameterValue(mock_ack_policy, value_type=str),
                    "runtime_event_enabled": ParameterValue(runtime_event_enabled, value_type=bool),
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
                    "output_path": ParameterValue(probe_output_path, value_type=str),
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
    ])
