from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare("minimal_runtime_demo"),
        "config",
        "demo.yaml",
    ])

    return LaunchDescription([
        Node(
            package="minimal_runtime_demo",
            executable="input_node",
            name="input_node",
            output="screen",
            parameters=[config_file],
        ),
        Node(
            package="minimal_runtime_demo",
            executable="planner_node",
            name="planner_node",
            output="screen",
            parameters=[config_file],
        ),
        Node(
            package="minimal_runtime_demo",
            executable="action_node",
            name="action_node",
            output="screen",
            parameters=[config_file],
        ),
        Node(
            package="minimal_runtime_demo",
            executable="control_node",
            name="control_node",
            output="screen",
            parameters=[config_file],
        ),
    ])
