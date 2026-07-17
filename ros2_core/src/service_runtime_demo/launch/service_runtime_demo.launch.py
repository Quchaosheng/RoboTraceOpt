from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    request_rate_hz = LaunchConfiguration("request_rate_hz")
    server_delay_ms = LaunchConfiguration("server_delay_ms")
    runtime_events_enabled = LaunchConfiguration("runtime_events_enabled")
    fault_every_n = LaunchConfiguration("fault_every_n")
    output_path = LaunchConfiguration("output_path")

    return LaunchDescription(
        [
            DeclareLaunchArgument("request_rate_hz", default_value="2.0"),
            DeclareLaunchArgument("server_delay_ms", default_value="0"),
            DeclareLaunchArgument("runtime_events_enabled", default_value="true"),
            DeclareLaunchArgument("fault_every_n", default_value="0"),
            DeclareLaunchArgument(
                "output_path", default_value="logs/service_runtime_events.jsonl"
            ),
            Node(
                package="service_runtime_demo",
                executable="service_server_node",
                name="service_runtime_server",
                output="screen",
                parameters=[
                    {
                        "runtime_events_enabled": ParameterValue(
                            runtime_events_enabled, value_type=bool
                        )
                    }
                ],
            ),
            Node(
                package="service_runtime_demo",
                executable="service_client_node",
                name="service_runtime_client",
                output="screen",
                parameters=[
                    {
                        "request_rate_hz": ParameterValue(request_rate_hz, value_type=float),
                        "server_delay_ms": ParameterValue(server_delay_ms, value_type=int),
                        "runtime_events_enabled": ParameterValue(
                            runtime_events_enabled, value_type=bool
                        ),
                        "fault_every_n": ParameterValue(fault_every_n, value_type=int),
                    }
                ],
            ),
            Node(
                package="runtime_logger_pkg",
                executable="runtime_event_logger_node",
                name="runtime_event_logger_node",
                output="screen",
                condition=IfCondition(runtime_events_enabled),
                parameters=[
                    {
                        "output_path": ParameterValue(output_path, value_type=str),
                        "flush_every_event": False,
                    }
                ],
            ),
        ]
    )
