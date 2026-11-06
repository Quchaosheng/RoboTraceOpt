cmake_minimum_required(VERSION 3.8)
project(can_bridge_pkg)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(ai_robot_runtime_interfaces REQUIRED)

add_executable(can_bridge_node src/can_bridge_node.cpp)
target_include_directories(can_bridge_node PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
target_compile_features(can_bridge_node PUBLIC cxx_std_17)
ament_target_dependencies(can_bridge_node
  rclcpp
  ai_robot_runtime_interfaces
)

install(TARGETS
  can_bridge_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include
)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_ack_terminal test/test_ack_terminal.cpp)
  target_include_directories(test_ack_terminal PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  )
  target_compile_features(test_ack_terminal PUBLIC cxx_std_17)
endif()

ament_package()
