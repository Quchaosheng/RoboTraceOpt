# robotraceopt_core

`robotraceopt_core` exposes the dependency-free C++ planner core as a ROS 2
Humble `ament_cmake` package. The package compiles the canonical sources from
`cpp_core/planner`; it does not maintain a second copy of the implementation.

## Build and test

Run these commands from the repository root after sourcing ROS 2 Humble:

```bash
colcon build \
  --base-paths ros2_core/src \
  --packages-select robotraceopt_core \
  --cmake-args -DBUILD_TESTING=ON
colcon test --packages-select robotraceopt_core
colcon test-result --verbose
```

## Consume from another ament package

Declare the package dependency in `package.xml`:

```xml
<depend>robotraceopt_core</depend>
```

Then link its exported target in `CMakeLists.txt`:

```cmake
find_package(robotraceopt_core REQUIRED)

add_executable(my_planner_node src/my_planner_node.cpp)
target_compile_features(my_planner_node PUBLIC cxx_std_17)
target_link_libraries(my_planner_node PRIVATE robotraceopt_core::planner)
```

Public headers are available under `robotraceopt/planner`, for example:

```cpp
#include <robotraceopt/planner/model_contract.hpp>
```

## Repository layout requirement

The package intentionally references `../../../cpp_core/planner` while it is
built. Normal colcon isolated builds and `--symlink-install` builds retain the
source tree and work with this layout. Copying only this package directory into
another workspace, or releasing it as a standalone source archive, will fail
because the canonical planner sources are absent. For standalone distribution,
package the repository root or install the root `RoboTraceOptCore` CMake project
and adapt this wrapper to consume that installed target.
