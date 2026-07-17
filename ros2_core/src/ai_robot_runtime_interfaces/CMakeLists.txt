cmake_minimum_required(VERSION 3.8)
project(ai_robot_runtime_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/TraceHeader.msg"
  "msg/CameraFrame.msg"
  "msg/PlannerCommand.msg"
  "msg/RuntimeEvent.msg"
  "action/RobotCommand.action"
  "srv/RuntimeQuery.srv"
)

install(DIRECTORY include/
  DESTINATION include/${PROJECT_NAME}
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
