cmake_minimum_required(VERSION 3.14)

project(robotraceopt_diagnosis LANGUAGES CXX)

add_library(robotraceopt_diagnosis
    src/association.cpp
    src/evidence_graph.cpp
    src/stage_window.cpp
    src/topology_contract.cpp
)
add_library(RoboTraceOpt::diagnosis ALIAS robotraceopt_diagnosis)

target_compile_features(robotraceopt_diagnosis PUBLIC cxx_std_17)
target_include_directories(robotraceopt_diagnosis
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

if(MSVC)
    target_compile_options(robotraceopt_diagnosis PRIVATE /W4 /permissive-)
else()
    target_compile_options(robotraceopt_diagnosis PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(CMAKE_SOURCE_DIR STREQUAL PROJECT_SOURCE_DIR)
    include(CTest)
    set(_robotraceopt_diagnosis_tests_default "${BUILD_TESTING}")
elseif(DEFINED ROBOTRACEOPT_BUILD_TESTS)
    set(_robotraceopt_diagnosis_tests_default "${ROBOTRACEOPT_BUILD_TESTS}")
else()
    set(_robotraceopt_diagnosis_tests_default ON)
endif()
option(
    ROBOTRACEOPT_DIAGNOSIS_BUILD_TESTS
    "Build diagnosis unit tests"
    "${_robotraceopt_diagnosis_tests_default}"
)
unset(_robotraceopt_diagnosis_tests_default)

if(ROBOTRACEOPT_DIAGNOSIS_BUILD_TESTS)
    enable_testing()
    add_executable(robotraceopt_diagnosis_tests tests/diagnosis_tests.cpp)
    target_link_libraries(robotraceopt_diagnosis_tests PRIVATE RoboTraceOpt::diagnosis)
    target_compile_features(robotraceopt_diagnosis_tests PRIVATE cxx_std_17)
    add_test(NAME robotraceopt_diagnosis_tests COMMAND robotraceopt_diagnosis_tests)
endif()
