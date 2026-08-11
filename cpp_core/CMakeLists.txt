cmake_minimum_required(VERSION 3.16)

project(
  RoboTraceOptCore
  VERSION 0.1.0
  DESCRIPTION "Portable C++ core for RoboTraceOpt diagnosis and optimization"
  LANGUAGES CXX
)

option(ROBOTRACEOPT_BUILD_TESTS "Build the C++ core tests" ON)
option(ROBOTRACEOPT_BUILD_EXAMPLES "Build the C++ core examples" ON)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)
if(ROBOTRACEOPT_BUILD_TESTS)
  include(CTest)
  enable_testing()
endif()

add_subdirectory(diagnosis)
add_subdirectory(planner)
add_subdirectory(optimizer)

set_target_properties(robotraceopt_diagnosis PROPERTIES EXPORT_NAME diagnosis)
set_target_properties(robotraceopt_optimizer PROPERTIES EXPORT_NAME optimizer)
set_target_properties(robotraceopt_planner PROPERTIES EXPORT_NAME planner)

if(ROBOTRACEOPT_BUILD_EXAMPLES)
  add_subdirectory(examples)
endif()

install(
  TARGETS
    robotraceopt_diagnosis
    robotraceopt_optimizer
    robotraceopt_planner
  EXPORT RoboTraceOptCoreTargets
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
  RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
  INCLUDES DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)
install(
  DIRECTORY
    diagnosis/include/robotraceopt
    optimizer/include/robotraceopt
    planner/include/robotraceopt
  DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)
install(
  EXPORT RoboTraceOptCoreTargets
  FILE RoboTraceOptCoreTargets.cmake
  NAMESPACE RoboTraceOpt::
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/RoboTraceOptCore
)

configure_package_config_file(
  cmake/RoboTraceOptCoreConfig.cmake.in
  ${CMAKE_CURRENT_BINARY_DIR}/RoboTraceOptCoreConfig.cmake
  INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/RoboTraceOptCore
)
write_basic_package_version_file(
  ${CMAKE_CURRENT_BINARY_DIR}/RoboTraceOptCoreConfigVersion.cmake
  VERSION ${PROJECT_VERSION}
  COMPATIBILITY SameMajorVersion
)
install(
  FILES
    ${CMAKE_CURRENT_BINARY_DIR}/RoboTraceOptCoreConfig.cmake
    ${CMAKE_CURRENT_BINARY_DIR}/RoboTraceOptCoreConfigVersion.cmake
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/RoboTraceOptCore
)
