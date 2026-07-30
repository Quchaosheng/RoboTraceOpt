#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo: sudo bash scripts/install_native_x86_dependencies.sh" >&2
  exit 2
fi
if grep -qi microsoft /proc/sys/kernel/osrelease; then
  echo "WSL is not an admissible F3/F4 formal host; use native Ubuntu." >&2
  exit 2
fi
if ! grep -q '^ID=ubuntu' /etc/os-release || ! grep -q '^VERSION_ID="22.04"' /etc/os-release; then
  echo "This package is qualified for native Ubuntu 22.04 only." >&2
  exit 2
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release software-properties-common
add-apt-repository -y universe
if [[ ! -f /usr/share/keyrings/ros-archive-keyring.gpg ]]; then
  curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
    -o /usr/share/keyrings/ros-archive-keyring.gpg
fi
printf 'deb [arch=%s signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu %s main\n' \
  "$(dpkg --print-architecture)" "$(. /etc/os-release && echo "${UBUNTU_CODENAME}")" \
  > /etc/apt/sources.list.d/ros2.list
apt-get update
apt-get install -y \
  build-essential \
  bpftrace \
  can-utils \
  linux-tools-common \
  python3-colcon-common-extensions \
  python3-pip \
  python3-rosdep \
  ros-humble-desktop \
  ros-humble-ros2trace \
  ros-humble-tracetools \
  stress-ng

if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
  rosdep init
fi
rosdep update
echo "Dependencies installed. Next run: sudo bash scripts/run_native_x86_f3_f4.sh"
