cmake_minimum_required(VERSION 3.16)
project(vlm_planner_cpp_pkg LANGUAGES CXX)

find_package(ament_cmake REQUIRED)
find_package(ai_robot_runtime_interfaces REQUIRED)
find_package(rclcpp REQUIRED)
find_package(robotraceopt_core REQUIRED)

add_library(vlm_planner_runtime_contract src/runtime_contract.cpp)
target_include_directories(vlm_planner_runtime_contract PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)
target_compile_features(vlm_planner_runtime_contract PUBLIC cxx_std_17)

add_library(vlm_planner_node_component src/vlm_planner_node.cpp)
target_include_directories(vlm_planner_node_component PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)
target_compile_features(vlm_planner_node_component PUBLIC cxx_std_17)
target_link_libraries(vlm_planner_node_component
  vlm_planner_runtime_contract robotraceopt_core::planner)
ament_target_dependencies(vlm_planner_node_component
  ai_robot_runtime_interfaces rclcpp)

add_executable(vlm_planner_node src/main.cpp)
target_compile_features(vlm_planner_node PUBLIC cxx_std_17)
target_link_libraries(vlm_planner_node vlm_planner_node_component)
ament_target_dependencies(vlm_planner_node rclcpp)

if(MSVC)
  target_compile_options(vlm_planner_runtime_contract PRIVATE /W4 /permissive-)
  target_compile_options(vlm_planner_node_component PRIVATE /W4 /permissive-)
else()
  target_compile_options(vlm_planner_runtime_contract PRIVATE -Wall -Wextra -Wpedantic)
  target_compile_options(vlm_planner_node_component PRIVATE -Wall -Wextra -Wpedantic)
endif()

install(TARGETS
  vlm_planner_runtime_contract
  vlm_planner_node_component
  vlm_planner_node
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_runtime_contract test/test_runtime_contract.cpp)
  target_compile_features(test_runtime_contract PRIVATE cxx_std_17)
  target_link_libraries(test_runtime_contract vlm_planner_runtime_contract)
endif()

ament_export_include_directories(include)
ament_export_dependencies(ai_robot_runtime_interfaces rclcpp robotraceopt_core)
ament_package()
