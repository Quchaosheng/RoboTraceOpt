cmake_minimum_required(VERSION 3.8)
project(runtime_logger_pkg)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(ai_robot_runtime_interfaces REQUIRED)

add_executable(runtime_event_logger_node src/runtime_event_logger_node.cpp)
target_include_directories(runtime_event_logger_node PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
target_compile_features(runtime_event_logger_node PUBLIC cxx_std_17)
ament_target_dependencies(runtime_event_logger_node
  rclcpp
  ai_robot_runtime_interfaces
)

install(TARGETS
  runtime_event_logger_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include
)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
