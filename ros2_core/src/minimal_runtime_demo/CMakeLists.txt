cmake_minimum_required(VERSION 3.8)
project(minimal_runtime_demo)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(ai_robot_runtime_interfaces REQUIRED)
find_package(std_msgs REQUIRED)

set(DEMO_NODES
  input_node
  planner_node
  action_node
  control_node
)

foreach(node_target IN LISTS DEMO_NODES)
  add_executable(${node_target} src/${node_target}.cpp)
  target_include_directories(${node_target}
    PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
  )
  ament_target_dependencies(${node_target}
    rclcpp
    ai_robot_runtime_interfaces
    std_msgs
  )
  install(
    TARGETS ${node_target}
    DESTINATION lib/${PROJECT_NAME}
  )
endforeach()

install(
  DIRECTORY include/
  DESTINATION include
)

install(
  DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
