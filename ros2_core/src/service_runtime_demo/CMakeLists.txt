cmake_minimum_required(VERSION 3.8)
project(service_runtime_demo)

find_package(ament_cmake REQUIRED)
find_package(ai_robot_runtime_interfaces REQUIRED)
find_package(rclcpp REQUIRED)

add_executable(service_client_node src/service_client_node.cpp)
target_include_directories(service_client_node PUBLIC include)
target_compile_features(service_client_node PUBLIC cxx_std_17)
ament_target_dependencies(service_client_node ai_robot_runtime_interfaces rclcpp)

add_executable(service_server_node src/service_server_node.cpp)
target_include_directories(service_server_node PUBLIC include)
target_compile_features(service_server_node PUBLIC cxx_std_17)
ament_target_dependencies(service_server_node ai_robot_runtime_interfaces rclcpp)

install(TARGETS service_client_node service_server_node DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_context_contract test/test_context_contract.cpp)
  target_include_directories(test_context_contract PUBLIC include)
  target_compile_features(test_context_contract PUBLIC cxx_std_17)
endif()

ament_package()
