#!/usr/bin/env bash
set -euo pipefail
akimbo_uid=${1:?user id required}
akimbo_data=${2:?data directory required}
akimbo_scripts=$(cd -- "$(dirname -- "$0")" && pwd)
[[ $akimbo_uid == "$(id -u)" && $akimbo_uid != 0 ]] || exit 1
sudo -v
sudo dnf install -y xrandr xprop git cargo rust gcc gcc-c++ libstdc++-static cmake make clang nasm \
  autoconf automake libtool pkgconf-pkg-config npm meson ninja-build \
  libX11-devel libXext-devel libXft-devel libXinerama-devel libXcursor-devel \
  libXrender-devel libXfixes-devel libXtst-devel libXrandr-devel libXcomposite-devel \
  libXi-devel libXv-devel libX11-xcb libxcb-devel libdrm-devel pango-devel \
  gstreamer1-devel gstreamer1-plugins-base-devel dbus-devel libva-devel libva-utils \
  wayland-devel wayland-protocols-devel libxkbcommon-devel mesa-libGL-devel \
  mesa-libEGL-devel libdecor-devel openssl-devel usbmuxd libimobiledevice-utils
sudo bash "$akimbo_scripts/setup-root.sh" "$akimbo_uid"
bash "$akimbo_scripts/build-weylus.sh" "$akimbo_data"
