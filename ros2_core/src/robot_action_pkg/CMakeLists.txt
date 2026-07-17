cmake_minimum_required(VERSION 3.8)
project(robot_action_pkg)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(ai_robot_runtime_interfaces REQUIRED)

add_executable(robot_action_node src/robot_action_node.cpp)
add_executable(action_manager_node src/action_manager_node.cpp)
target_include_directories(robot_action_node PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
target_include_directories(action_manager_node PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
target_compile_features(robot_action_node PUBLIC cxx_std_17)
target_compile_features(action_manager_node PUBLIC cxx_std_17)
ament_target_dependencies(robot_action_node
  rclcpp
  ai_robot_runtime_interfaces
)
ament_target_dependencies(action_manager_node
  rclcpp
  rclcpp_action
  ai_robot_runtime_interfaces
)

install(TARGETS
  robot_action_node
  action_manager_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include
)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
