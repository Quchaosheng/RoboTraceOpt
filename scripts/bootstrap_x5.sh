#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --dry-run|--apply"
}

if [[ $# -ne 1 || ( "$1" != "--dry-run" && "$1" != "--apply" ) ]]; then
  usage >&2
  exit 2
fi

mode="$1"
packages=(
  build-essential
  bpftool
  can-utils
  clang
  cmake
  curl
  git
  iproute2
  jq
  libbpf-dev
  libelf-dev
  lld
  llvm
  ninja-build
  pkg-config
  python3-pip
  python3-rosdep
  python3-venv
  stress-ng
  zlib1g-dev
)

printf 'apt-get install -y'
printf ' %q' "${packages[@]}"
printf '\n'
echo "Optional ROS packages: python3-colcon-common-extensions ros-humble-ros-base ros-humble-ros2-tracing ros-humble-tracetools ros-humble-rmw-cyclonedds-cpp"

if [[ "$mode" == "--dry-run" ]]; then
  exit 0
fi

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "Refusing to apply: expected aarch64, found $(uname -m)." >&2
  exit 2
fi

source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "22.04" ]]; then
  echo "Refusing to apply: Ubuntu 22.04 is required." >&2
  exit 2
fi

echo "Executing apt-get update and package installation."
sudo apt-get update
sudo apt-get install -y "${packages[@]}"

ros_packages=(
  python3-colcon-common-extensions
  ros-humble-ros-base
  ros-humble-ros2-tracing
  ros-humble-tracetools
  ros-humble-rmw-cyclonedds-cpp
)
if apt-cache show ros-humble-ros-base >/dev/null 2>&1; then
  sudo apt-get install -y "${ros_packages[@]}"
else
  echo "ROS 2 apt repository is not configured; install ROS 2 Humble from the official repository before running preflight." >&2
fi

echo "Bootstrap complete. Reboot only if your board vendor's kernel packages required it."
