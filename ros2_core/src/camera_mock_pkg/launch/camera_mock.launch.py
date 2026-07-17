import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    config_file = os.path.join(
        get_package_share_directory("camera_mock_pkg"),
        "config",
        "camera_mock.yaml",
    )

    return LaunchDescription([
        Node(
            package="camera_mock_pkg",
            executable="camera_mock_node",
            name="camera_mock_node",
            output="screen",
            parameters=[config_file],
        ),
    ])
