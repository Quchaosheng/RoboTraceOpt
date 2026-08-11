cmake_minimum_required(VERSION 3.16)

project(robotraceopt_optimizer LANGUAGES CXX)

add_library(robotraceopt_optimizer
    src/candidate_sampler.cpp
    src/runtime_objective.cpp
    src/validation.cpp
)
add_library(RoboTraceOpt::optimizer ALIAS robotraceopt_optimizer)

target_compile_features(robotraceopt_optimizer PUBLIC cxx_std_17)
target_include_directories(robotraceopt_optimizer
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

if(MSVC)
    target_compile_options(robotraceopt_optimizer PRIVATE /W4 /permissive-)
else()
    target_compile_options(robotraceopt_optimizer PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(CMAKE_SOURCE_DIR STREQUAL PROJECT_SOURCE_DIR)
    include(CTest)
    set(_robotraceopt_optimizer_tests_default "${BUILD_TESTING}")
elseif(DEFINED ROBOTRACEOPT_BUILD_TESTS)
    set(_robotraceopt_optimizer_tests_default "${ROBOTRACEOPT_BUILD_TESTS}")
else()
    set(_robotraceopt_optimizer_tests_default ON)
endif()
option(
    ROBOTRACEOPT_OPTIMIZER_BUILD_TESTS
    "Build optimizer unit tests"
    "${_robotraceopt_optimizer_tests_default}"
)
unset(_robotraceopt_optimizer_tests_default)

if(ROBOTRACEOPT_OPTIMIZER_BUILD_TESTS)
    enable_testing()
    add_executable(robotraceopt_optimizer_tests tests/test_optimizer.cpp)
    target_link_libraries(robotraceopt_optimizer_tests PRIVATE RoboTraceOpt::optimizer)
    target_compile_features(robotraceopt_optimizer_tests PRIVATE cxx_std_17)
    add_test(NAME robotraceopt_optimizer_tests COMMAND robotraceopt_optimizer_tests)
endif()
