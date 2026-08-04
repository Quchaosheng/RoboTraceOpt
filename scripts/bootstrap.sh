#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/bootstrap.sh [--profile auto|native-x86-2404|x5] --dry-run|--apply

Profiles:
  auto                 Detect a supported Ubuntu host.
  native-x86-2404      Native x86_64 Ubuntu 24.04 with ROS 2 Jazzy.
  x5                   ARM64 Ubuntu 22.04 with ROS 2 Humble.

Use --dry-run first. The native x86 apply path must be run with sudo.
EOF
}

profile=auto
mode=""
while (($#)); do
  case "$1" in
    --profile)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      profile=$2
      shift 2
      ;;
    --dry-run|--apply)
      [[ -z "$mode" ]] || { usage >&2; exit 2; }
      mode=$1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

[[ -n "$mode" ]] || { usage >&2; exit 2; }

read_host() {
  host_arch=$(uname -m)
  host_os=unknown
  host_version=unknown
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    host_os=${ID:-unknown}
    host_version=${VERSION_ID:-unknown}
  fi
}

detect_profile() {
  read_host
  case "${host_arch}:${host_os}:${host_version}" in
    x86_64:ubuntu:24.04|amd64:ubuntu:24.04)
      profile=native-x86-2404
      ;;
    aarch64:ubuntu:22.04|arm64:ubuntu:22.04)
      profile=x5
      ;;
    *)
      echo "Unsupported host: arch=${host_arch} os=${host_os} version=${host_version}." >&2
      echo "Select --profile explicitly for a dry run, or use a supported native host." >&2
      exit 2
      ;;
  esac
}

validate_apply_host() {
  local expected_profile=$1
  read_host
  case "$expected_profile" in
    native-x86-2404)
      [[ "$host_arch" == x86_64 || "$host_arch" == amd64 ]] || return 1
      [[ "$host_os" == ubuntu && "$host_version" == 24.04 ]] || return 1
      ;;
    x5)
      [[ "$host_arch" == aarch64 || "$host_arch" == arm64 ]] || return 1
      [[ "$host_os" == ubuntu && "$host_version" == 22.04 ]] || return 1
      ;;
    *)
      return 1
      ;;
  esac
}

[[ "$profile" == auto ]] && detect_profile
case "$profile" in
  native-x86-2404|x5) ;;
  *)
    usage >&2
    exit 2
    ;;
esac

echo "bootstrap_profile=$profile"
if [[ "$mode" == --dry-run ]]; then
  case "$profile" in
    native-x86-2404)
      echo "sudo bash scripts/install_native_x86_2404_dependencies.sh"
      ;;
    x5)
      bash "${SCRIPT_DIR}/bootstrap_x5.sh" --dry-run
      ;;
  esac
  exit 0
fi

if ! validate_apply_host "$profile"; then
  echo "Refusing to apply profile '$profile' on arch=${host_arch} os=${host_os} version=${host_version}." >&2
  exit 2
fi

case "$profile" in
  native-x86-2404)
    if [[ "$(id -u)" -ne 0 ]]; then
      echo "Run with sudo: sudo bash scripts/bootstrap.sh --profile native-x86-2404 --apply" >&2
      exit 2
    fi
    exec bash "${SCRIPT_DIR}/install_native_x86_2404_dependencies.sh"
    ;;
  x5)
    exec bash "${SCRIPT_DIR}/bootstrap_x5.sh" --apply
    ;;
esac
