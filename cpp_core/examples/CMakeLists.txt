add_executable(robotraceopt_core_demo traceopt_demo.cpp)
target_link_libraries(
  robotraceopt_core_demo
  PRIVATE
    RoboTraceOpt::diagnosis
    RoboTraceOpt::optimizer
    RoboTraceOpt::planner
)
target_compile_features(robotraceopt_core_demo PRIVATE cxx_std_17)

if(MSVC)
  target_compile_options(robotraceopt_core_demo PRIVATE /W4 /permissive-)
else()
  target_compile_options(robotraceopt_core_demo PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(ROBOTRACEOPT_BUILD_TESTS)
  add_test(NAME robotraceopt_core_demo COMMAND robotraceopt_core_demo)
endif()
