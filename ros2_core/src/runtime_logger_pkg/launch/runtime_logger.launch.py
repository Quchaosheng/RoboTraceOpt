import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    config_file = os.path.join(
        get_package_share_directory("runtime_logger_pkg"),
        "config",
        "runtime_logger.yaml",
    )

    output_path = LaunchConfiguration("output_path")
    flush_every_event = LaunchConfiguration("flush_every_event")

    return LaunchDescription([
        DeclareLaunchArgument(
            "output_path",
            default_value="logs/runtime_events.jsonl",
            description="JSONL file path for RuntimeEvent records.",
        ),
        DeclareLaunchArgument(
            "flush_every_event",
            default_value="true",
            description="Flush the JSONL file after every event.",
        ),
        Node(
            package="runtime_logger_pkg",
            executable="runtime_event_logger_node",
            name="runtime_event_logger_node",
            output="screen",
            parameters=[
                config_file,
                {
                    "output_path": ParameterValue(output_path, value_type=str),
                    "flush_every_event": ParameterValue(flush_every_event, value_type=bool),
                },
            ],
        ),
    ])
