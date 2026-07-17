#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SAFE_ROOT="${ROS2_RUNTIME_SAFE_ROOT:-${HOME}/.cache/robotracert_fusion_build}"
INSTALL_SETUP="${SAFE_ROOT}/install/setup.bash"

usage() {
  echo "usage: $0 {w1|w2|w3|all} [duration_seconds]" >&2
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage
  exit 2
fi

WORKLOAD="$1"
DURATION_SECONDS="${2:-8}"
if [[ ! "${DURATION_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: duration_seconds must be a positive integer" >&2
  exit 2
fi
if [[ ! -f "${INSTALL_SETUP}" ]]; then
  echo "error: build setup not found: ${INSTALL_SETUP}" >&2
  echo "run scripts/build_core.sh first with the same ROS2_RUNTIME_SAFE_ROOT" >&2
  exit 1
fi

set +u
# shellcheck disable=SC1090
source "${INSTALL_SETUP}"
set -u

run_one() {
  local workload="$1"
  local output_dir="${PROJECT_ROOT}/data/raw/smoke/${workload}"
  local events_path="${output_dir}/runtime_events.jsonl"
  local launch_log="${output_dir}/launch.log"
  local summary_path="${output_dir}/summary.json"
  local process_manifest_path="${PROCESS_MANIFEST_PATH:-}"
  local expected_processes=0
  local launch_command=()

  mkdir -p "${output_dir}" "${SAFE_ROOT}/ros_logs/${workload}"
  rm -f "${events_path}" "${launch_log}" "${summary_path}"
  if [[ -n "${process_manifest_path}" ]]; then
    rm -f "${process_manifest_path}"
  fi

  case "${workload}" in
    "w1")
      expected_processes=4
      launch_command=(
        ros2 launch runtime_bringup ai_runtime.launch.py
        profile:=enhanced camera_rate_hz:=4.0 planner_backend:=mock
        action_manager_enabled:=true ack_mode:=mock mock_mode:=true
        output_path:="${events_path}"
      )
      ;;
    "w2")
      expected_processes=2
      launch_command=(
        ros2 launch service_runtime_demo service_runtime_demo.launch.py
        request_rate_hz:=5.0 server_delay_ms:=20
        runtime_events_enabled:=true output_path:="${events_path}"
      )
      ;;
    "w3")
      expected_processes=4
      launch_command=(
        ros2 launch runtime_bringup ai_runtime.launch.py
        profile:=baseline input_rate_hz:=5.0 planner_delay_ms:=20
        action_delay_ms:=30 control_delay_ms:=10
        runtime_event_enabled:=true output_path:="${events_path}"
      )
      ;;
    *)
      echo "error: unknown workload: ${workload}" >&2
      usage
      return 2
      ;;
  esac

  echo "running ${workload} for ${DURATION_SECONDS}s"
  set +e
  if [[ -n "${process_manifest_path}" ]]; then
    ROS_LOG_DIR="${SAFE_ROOT}/ros_logs/${workload}" \
      timeout --signal=INT --kill-after=3s "${DURATION_SECONDS}s" \
      "${launch_command[@]}" >"${launch_log}" 2>&1 &
    local launch_pid=$!
    local manifest_captured=false
    for _ in $(seq 1 30); do
      sleep 0.2
      if [[ -s "${events_path}" ]] && python3 "${SCRIPT_DIR}/capture_process_manifest.py" \
        --runtime-events "${events_path}" \
        --minimum-processes "${expected_processes}" \
        --repo-root "${PROJECT_ROOT}" \
        --output "${process_manifest_path}" >/dev/null 2>&1; then
        manifest_captured=true
        break
      fi
    done
    wait "${launch_pid}"
    local launch_status=$?
    if [[ "${manifest_captured}" != true ]]; then
      echo "error: could not capture live process manifest for ${workload}" >&2
      set -e
      return 1
    fi
  else
    ROS_LOG_DIR="${SAFE_ROOT}/ros_logs/${workload}" \
      timeout --signal=INT --kill-after=3s "${DURATION_SECONDS}s" \
      "${launch_command[@]}" >"${launch_log}" 2>&1
    local launch_status=$?
  fi
  set -e
  if [[ ${launch_status} -ne 124 && ${launch_status} -ne 130 ]]; then
    echo "error: ${workload} launch failed with status ${launch_status}" >&2
    echo "see ${launch_log}" >&2
    return "${launch_status}"
  fi

  python3 "${SCRIPT_DIR}/check_smoke_outputs.py" \
    --workload "${workload}" \
    --input "${events_path}" \
    --minimum-traces 2 \
    --output-json "${summary_path}"
}

case "${WORKLOAD}" in
  "w1"|"w2"|"w3")
    run_one "${WORKLOAD}"
    ;;
  "all")
    for workload in w1 w2 w3; do
      run_one "${workload}"
    done
    ;;
  *)
    echo "error: unknown workload: ${WORKLOAD}" >&2
    usage
    exit 2
    ;;
esac
