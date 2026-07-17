import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    config_file = os.path.join(
        get_package_share_directory("can_bridge_pkg"),
        "config",
        "can_bridge.yaml",
    )

    return LaunchDescription([
        Node(
            package="can_bridge_pkg",
            executable="can_bridge_node",
            name="can_bridge_node",
            output="screen",
            parameters=[config_file],
        ),
    ])
