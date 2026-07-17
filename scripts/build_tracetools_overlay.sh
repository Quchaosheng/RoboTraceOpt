#!/usr/bin/env bash
set -euo pipefail

TRACETOOLS_VERSION="4.1.2"
TRACETOOLS_COMMIT="3c159b382d2d565e26eaa91e39c9ec06a5c6fe88"
OVERLAY_ROOT="${TRACETOOLS_OVERLAY_ROOT:-${HOME}/.cache/robotracert_tracing_overlay}"
SOURCE_ROOT="${OVERLAY_ROOT}/src/ros2_tracing"

if ! pkg-config --exists lttng-ust; then
  echo "error: lttng-ust development files are required" >&2
  exit 1
fi

if [[ ! -d "${SOURCE_ROOT}/.git" ]]; then
  mkdir -p "${OVERLAY_ROOT}/src"
  git clone --depth 1 --branch "${TRACETOOLS_VERSION}" \
    https://github.com/ros2/ros2_tracing.git "${SOURCE_ROOT}"
fi

observed_commit="$(git -C "${SOURCE_ROOT}" rev-parse HEAD)"
if [[ "${observed_commit}" != "${TRACETOOLS_COMMIT}" ]]; then
  echo "error: expected ros2_tracing ${TRACETOOLS_COMMIT}, found ${observed_commit}" >&2
  exit 1
fi

set +u
# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
set -u

cd "${OVERLAY_ROOT}"
colcon --log-base log build \
  --packages-select tracetools \
  --allow-overriding tracetools \
  --build-base build \
  --install-base install \
  --cmake-args -DTRACETOOLS_DISABLED=OFF -DTRACETOOLS_STATUS_CHECKING_TOOL=ON

set +u
# shellcheck disable=SC1091
source "${OVERLAY_ROOT}/install/setup.bash"
set -u
ros2 run tracetools status

echo "tracetools overlay ready: ${OVERLAY_ROOT}/install/setup.bash"
