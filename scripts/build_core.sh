#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_ROOT="${PROJECT_ROOT}/ros2_core"

SAFE_ROOT="${ROS2_RUNTIME_SAFE_ROOT:-${HOME}/.cache/robotraceopt_build}"
SAFE_WS="${SAFE_ROOT}/ws"
BUILD_BASE="${SAFE_ROOT}/build"
INSTALL_BASE="${SAFE_ROOT}/install"
LOG_BASE="${SAFE_ROOT}/log"
WORKSPACE_MARKER="${SAFE_ROOT}/workspace_root"
CURRENT_WORKSPACE="$(realpath "${WORKSPACE_ROOT}")"
CACHED_WORKSPACE=""

if [[ -f /opt/ros/humble/setup.bash ]]; then
  set +u
  # shellcheck disable=SC1091
  source /opt/ros/humble/setup.bash
  set -u
else
  echo "error: /opt/ros/humble/setup.bash not found. Please install or source ROS2 Humble first." >&2
  exit 1
fi

mkdir -p "${SAFE_ROOT}"
if [[ -f "${WORKSPACE_MARKER}" ]]; then
  CACHED_WORKSPACE="$(cat "${WORKSPACE_MARKER}")"
fi
if [[ ! -f "${WORKSPACE_MARKER}" ]] || [[ "${CACHED_WORKSPACE}" != "${CURRENT_WORKSPACE}" ]]; then
  rm -rf -- "${BUILD_BASE}" "${INSTALL_BASE}"
fi
printf '%s\n' "${CURRENT_WORKSPACE}" > "${WORKSPACE_MARKER}"
ln -sfn "${WORKSPACE_ROOT}" "${SAFE_WS}"

cd "${SAFE_WS}"
colcon --log-base "${LOG_BASE}" build \
  --packages-select ai_robot_runtime_interfaces minimal_runtime_demo service_runtime_demo runtime_logger_pkg camera_mock_pkg vlm_planner_pkg robot_action_pkg can_bridge_pkg runtime_bringup \
  --build-base "${BUILD_BASE}" \
  --install-base "${INSTALL_BASE}"

cat <<EOF

Core packages built successfully.

Use this setup file before running the demo:
  source ${INSTALL_BASE}/setup.bash

Recommended runtime commands:
  cd ${WORKSPACE_ROOT}
  source ${INSTALL_BASE}/setup.bash
  ros2 launch runtime_bringup ai_runtime.launch.py profile:=baseline output_path:=../data/logs/runtime_events.jsonl

Enhanced runtime:
  cd ${WORKSPACE_ROOT}
  source ${INSTALL_BASE}/setup.bash
  ros2 launch runtime_bringup ai_runtime.launch.py profile:=enhanced output_path:=../data/logs/runtime_events.jsonl

Service workload:
  cd ${WORKSPACE_ROOT}
  source ${INSTALL_BASE}/setup.bash
  ros2 launch service_runtime_demo service_runtime_demo.launch.py
EOF
