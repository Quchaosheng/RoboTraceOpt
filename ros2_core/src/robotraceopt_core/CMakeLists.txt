cmake_minimum_required(VERSION 3.8)
project(robotraceopt_core VERSION 0.1.0 LANGUAGES CXX)

find_package(ament_cmake REQUIRED)

get_filename_component(
  ROBOTRACEOPT_REPOSITORY_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../../.."
  ABSOLUTE
)
set(ROBOTRACEOPT_PLANNER_SOURCE_DIR
  "${ROBOTRACEOPT_REPOSITORY_ROOT}/cpp_core/planner"
)

if(NOT EXISTS "${ROBOTRACEOPT_PLANNER_SOURCE_DIR}/src/model_contract.cpp")
  message(FATAL_ERROR
    "The robotraceopt_core ROS package must be built from the RoboTraceOpt "
    "repository: missing ${ROBOTRACEOPT_PLANNER_SOURCE_DIR}"
  )
endif()

add_library(robotraceopt_core_planner STATIC
  "${ROBOTRACEOPT_PLANNER_SOURCE_DIR}/src/clients.cpp"
  "${ROBOTRACEOPT_PLANNER_SOURCE_DIR}/src/model_admission.cpp"
  "${ROBOTRACEOPT_PLANNER_SOURCE_DIR}/src/model_contract.cpp"
)
add_library(robotraceopt_core::planner ALIAS robotraceopt_core_planner)
set_target_properties(robotraceopt_core_planner PROPERTIES
  EXPORT_NAME planner
  POSITION_INDEPENDENT_CODE ON
)
target_compile_features(robotraceopt_core_planner PUBLIC cxx_std_17)
target_include_directories(robotraceopt_core_planner
  PUBLIC
    $<BUILD_INTERFACE:${ROBOTRACEOPT_PLANNER_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(robotraceopt_core_planner PRIVATE
    -Wall -Wextra -Wpedantic
  )
elseif(MSVC)
  target_compile_options(robotraceopt_core_planner PRIVATE /W4 /permissive-)
endif()

install(
  TARGETS robotraceopt_core_planner
  EXPORT robotraceopt_coreTargets
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION bin
  INCLUDES DESTINATION include
)
install(
  DIRECTORY "${ROBOTRACEOPT_PLANNER_SOURCE_DIR}/include/"
  DESTINATION include
)

if(BUILD_TESTING)
  enable_testing()
  add_executable(robotraceopt_core_contract_test
    test/test_planner_contract.cpp
  )
  target_compile_features(robotraceopt_core_contract_test PRIVATE cxx_std_17)
  target_link_libraries(robotraceopt_core_contract_test
    PRIVATE robotraceopt_core::planner
  )
  add_test(
    NAME robotraceopt_core_contract_test
    COMMAND $<TARGET_FILE:robotraceopt_core_contract_test>
  )
endif()

ament_export_targets(robotraceopt_coreTargets HAS_LIBRARY_TARGET)
ament_package()
