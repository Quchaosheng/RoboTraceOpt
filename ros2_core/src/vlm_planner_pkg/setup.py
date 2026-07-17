from glob import glob
import os

from setuptools import find_packages, setup


package_name = "vlm_planner_pkg"

setup(
    name=package_name,
    version="0.0.1",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    py_modules=["vlm_planner_node"],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="todo",
    maintainer_email="todo@example.com",
    description="Multi-backend VLM planner node for the AI Robotics Runtime.",
    license="TODO",
    entry_points={
        "console_scripts": [
            "vlm_planner_node = vlm_planner_node:main",
        ],
    },
)
