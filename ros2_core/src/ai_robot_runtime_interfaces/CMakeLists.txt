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

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_reaping_thread_group test/test_reaping_thread_group.cpp)
  target_include_directories(test_reaping_thread_group PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  )
  target_compile_features(test_reaping_thread_group PUBLIC cxx_std_17)
  find_package(Threads REQUIRED)
  target_link_libraries(test_reaping_thread_group Threads::Threads)
endif()

ament_package()
