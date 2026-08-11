cmake_minimum_required(VERSION 3.8)
project(runtime_bringup)

find_package(ament_cmake REQUIRED)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(
    ai_runtime_launch_contract
    test/test_ai_runtime_launch_contract.py
  )
endif()

ament_package()
