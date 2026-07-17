cmake_minimum_required(VERSION 3.8)
project(camera_mock_pkg)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(ai_robot_runtime_interfaces REQUIRED)

add_executable(camera_mock_node src/camera_mock_node.cpp)
target_include_directories(camera_mock_node PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
target_compile_features(camera_mock_node PUBLIC cxx_std_17)
ament_target_dependencies(camera_mock_node
  rclcpp
  ai_robot_runtime_interfaces
)

install(TARGETS camera_mock_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include
)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
