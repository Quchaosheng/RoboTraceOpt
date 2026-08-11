cmake_minimum_required(VERSION 3.16)

project(robotraceopt_planner LANGUAGES CXX)

add_library(robotraceopt_planner
    src/clients.cpp
    src/model_admission.cpp
    src/model_contract.cpp
)
add_library(RoboTraceOpt::planner ALIAS robotraceopt_planner)

target_compile_features(robotraceopt_planner PUBLIC cxx_std_17)
target_include_directories(robotraceopt_planner
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

if(MSVC)
    target_compile_options(robotraceopt_planner PRIVATE /W4 /permissive-)
else()
    target_compile_options(robotraceopt_planner PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(CMAKE_SOURCE_DIR STREQUAL PROJECT_SOURCE_DIR)
    include(CTest)
    set(_robotraceopt_planner_tests_default "${BUILD_TESTING}")
elseif(DEFINED ROBOTRACEOPT_BUILD_TESTS)
    set(_robotraceopt_planner_tests_default "${ROBOTRACEOPT_BUILD_TESTS}")
else()
    set(_robotraceopt_planner_tests_default ON)
endif()
option(
    ROBOTRACEOPT_PLANNER_BUILD_TESTS
    "Build planner core unit tests"
    "${_robotraceopt_planner_tests_default}"
)
unset(_robotraceopt_planner_tests_default)

if(ROBOTRACEOPT_PLANNER_BUILD_TESTS)
    enable_testing()
    add_executable(robotraceopt_planner_tests tests/planner_core_tests.cpp)
    target_link_libraries(robotraceopt_planner_tests PRIVATE RoboTraceOpt::planner)
    target_compile_features(robotraceopt_planner_tests PRIVATE cxx_std_17)
    if(MSVC)
        target_compile_options(robotraceopt_planner_tests PRIVATE /W4 /permissive-)
    else()
        target_compile_options(robotraceopt_planner_tests PRIVATE -Wall -Wextra -Wpedantic)
    endif()
    add_test(NAME robotraceopt_planner_tests COMMAND robotraceopt_planner_tests)
endif()
