#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_ROOT="${ROS2_RUNTIME_SAFE_ROOT:-${HOME}/.cache/robotraceopt_build}"
OVERLAY_ROOT="${TRACETOOLS_OVERLAY_ROOT:-${HOME}/.cache/robotracert_tracing_overlay}"
TRACE_ROOT="${TRACETOOLS_TRACE_ROOT:-${HOME}/.cache/robotracert_fusion_traces}"

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 {w1|w2|w3} [duration_seconds]" >&2
  exit 2
fi
workload="$1"
duration_seconds="${2:-8}"
if [[ ! "${workload}" =~ ^w[123]$ || ! "${duration_seconds}" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: invalid workload or duration" >&2
  exit 2
fi

for setup_file in \
  /opt/ros/humble/setup.bash \
  "${BUILD_ROOT}/install/setup.bash" \
  "${OVERLAY_ROOT}/install/setup.bash"
do
  if [[ ! -f "${setup_file}" ]]; then
    echo "error: setup file is missing: ${setup_file}" >&2
    exit 1
  fi
  set +u
  # shellcheck disable=SC1090
  source "${setup_file}"
  set -u
done

if ! ros2 run tracetools status | grep -qx "Tracing enabled"; then
  echo "error: tracetools provider is not enabled" >&2
  exit 1
fi

session="robotracert_${workload}_$(date -u +%Y%m%dT%H%M%SZ)_$$"
trace_dir="${TRACE_ROOT}/${session}"
evidence_dir="${PROJECT_ROOT}/data/raw/tracing/${session}"
clock_report="${evidence_dir}/clock_calibration.json"
process_manifest="${evidence_dir}/process_manifest.json"
if [[ -e "${trace_dir}" ]]; then
  echo "error: trace directory already exists: ${trace_dir}" >&2
  exit 1
fi
mkdir -p "${evidence_dir}"

python3 -m diagnosis.adapters.clock_calibration \
  --host-id "$(hostname)" \
  --sample-count 1000 \
  --tolerance-ns 100000 \
  --output "${clock_report}"

cleanup() {
  lttng stop "${session}" >/dev/null 2>&1 || true
  lttng destroy "${session}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

lttng create "${session}" --output="${trace_dir}"
lttng enable-event --userspace "ros2:*"
lttng add-context --userspace --type=vpid --type=vtid --type=procname
lttng start "${session}"

cd "${PROJECT_ROOT}"
PROCESS_MANIFEST_PATH="${process_manifest}" \
  bash "${SCRIPT_DIR}/run_smoke_workload.sh" "${workload}" "${duration_seconds}"

lttng stop "${session}"
lttng destroy "${session}"
trap - EXIT INT TERM

echo "trace directory: ${trace_dir}"
echo "evidence directory: ${evidence_dir}"
