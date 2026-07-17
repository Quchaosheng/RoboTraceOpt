import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    config_file = os.path.join(
        get_package_share_directory("robot_action_pkg"),
        "config",
        "robot_action.yaml",
    )

    return LaunchDescription([
        Node(
            package="robot_action_pkg",
            executable="action_manager_node",
            name="action_manager_node",
            output="screen",
            parameters=[config_file],
        ),
    ])
