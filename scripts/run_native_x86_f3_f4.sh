#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo: sudo bash scripts/run_native_x86_f3_f4.sh" >&2
  exit 2
fi
if grep -qi microsoft /proc/sys/kernel/osrelease; then
  echo "WSL is not an admissible F3/F4 formal host." >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_ID="native_x86_f3f4_$(date -u +%Y%m%d_%H%M%S)"
OUTPUT_ROOT="${PROJECT_ROOT}/data/raw/experiments/test/${RUN_ID}"
CAPABILITY_PATH="${PROJECT_ROOT}/data/raw/environment/${RUN_ID}_capabilities.json"

cd "${PROJECT_ROOT}"
bash scripts/build_core.sh
source "${HOME}/.cache/robotraceopt_build/install/setup.bash"

python3 scripts/check_platform_capabilities.py \
  --label native-x86-ubuntu-22.04 \
  --output-json "${CAPABILITY_PATH}" \
  --output-md "${CAPABILITY_PATH%.json}.md"

python3 scripts/run_formal_experiment_session.py \
  --matrix experiments/protocol/formal_experiment_matrix.json \
  --capability-report "${CAPABILITY_PATH}" \
  --case diagnosis_f3_control \
  --case diagnosis_f3_injected \
  --case diagnosis_f4_control \
  --case diagnosis_f4_injected \
  --dataset-role test \
  --session-name "${RUN_ID}" \
  --seed 20260729 \
  --output-dir "${OUTPUT_ROOT}"

echo
echo "F3/F4 session completed: ${OUTPUT_ROOT}"
echo "Copy this directory back for analysis, together with: ${CAPABILITY_PATH}"
