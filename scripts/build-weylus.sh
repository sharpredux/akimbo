#!/usr/bin/env bash
set -euo pipefail
akimbo_data=${1:?data directory required}
akimbo_script=$(realpath "$0")
# Keep this build off the desktop's unrestricted memory/CPU budget. nproc in
# upstream dependency scripts respects inherited CPU affinity as well.
if [[ ${AKIMBO_LIMITED_BUILD:-0} != 1 ]]; then
    akimbo_cpu=$(python3 -c 'import os; print(min(os.sched_getaffinity(0)))')
    exec systemd-run --user --unit=akimbo-build --collect --wait --pipe \
      --property=MemoryHigh=1G --property=MemoryMax=1536M \
      --property=MemorySwapMax=512M --property=CPUQuota=100% --property=Nice=10 \
      --setenv=AKIMBO_LIMITED_BUILD=1 \
      taskset -c "$akimbo_cpu" bash "$akimbo_script" "$akimbo_data"
fi
akimbo_commit=38a01a8f8e429500c7e9f67fc1c88ca37a4d1e93
akimbo_build="$akimbo_data/build/weylus-$akimbo_commit"
mkdir -p "$akimbo_data/bin" "$akimbo_data/build"
exec 9>"$akimbo_data/build/build.lock"
flock -n 9 || { echo 'Another Akimbo build is already running.' >&2; exit 1; }
export CARGO_BUILD_JOBS=1 CMAKE_BUILD_PARALLEL_LEVEL=1
# Full-program LTO can exceed the RAM available on smaller laptops.
export CARGO_PROFILE_RELEASE_LTO=false
# FLTK links libsupc++ statically on Fedora. Older installs may lack the
# libstdc++-static package; recover it as a local build dependency without sudo.
if [[ $(g++ -print-file-name=libsupc++.a) == libsupc++.a ]]; then
    akimbo_cxx="$akimbo_data/build/cxx-runtime"
    mkdir -p "$akimbo_cxx"
    if [[ ! -f "$akimbo_cxx/libsupc++.a" ]]; then
        dnf download --destdir "$akimbo_cxx" "libstdc++-static.$(uname -m)"
        for akimbo_rpm in "$akimbo_cxx"/*.rpm; do
            (cd "$akimbo_cxx" && rpm2cpio "$akimbo_rpm" | cpio -idm --no-absolute-filenames --quiet)
        done
        akimbo_archive=$(find "$akimbo_cxx/usr" -name libsupc++.a -print -quit)
        [[ -n $akimbo_archive ]] || { echo 'Cannot locate libsupc++.a in Fedora package.' >&2; exit 1; }
        cp "$akimbo_archive" "$akimbo_cxx/libsupc++.a"
    fi
    export LIBRARY_PATH="$akimbo_cxx${LIBRARY_PATH:+:$LIBRARY_PATH}"
fi
if [[ -x "$akimbo_data/bin/weylus" && -f "$akimbo_data/bin/weylus.commit" ]] && \
   [[ $(<"$akimbo_data/bin/weylus.commit") == "$akimbo_commit" ]]; then
    echo 'Pinned Weylus is already built.'
    exit 0
fi
if [[ ! -d "$akimbo_build/.git" ]]; then
    git clone https://github.com/H-M-H/Weylus.git "$akimbo_build"
fi
git -C "$akimbo_build" checkout --detach "$akimbo_commit"
[[ $(git -C "$akimbo_build" rev-parse HEAD) == "$akimbo_commit" ]]
install -m 0755 "$(dirname "$akimbo_script")/ffmpeg-minimal.sh" "$akimbo_build/deps/ffmpeg.sh"
# Local tool dependency, never a global npm install.
npm install --prefix "$akimbo_data/build/typescript" --no-audit --no-fund typescript@5.7.3
export PATH="$akimbo_data/build/typescript/node_modules/.bin:$PATH"
cd "$akimbo_build"
# Bundled FFmpeg/x264 uses upstream's pinned dependency revisions.
# Resume an interrupted dependency build before invoking Cargo. Upstream only
# tests whether dist_linux exists, even if the previous build was incomplete.
akimbo_complete=1
for akimbo_lib in avdevice avformat avfilter avcodec swresample swscale avutil x264; do
    [[ -f "deps/dist_linux/lib/lib$akimbo_lib.a" ]] || akimbo_complete=0
done
if [[ $akimbo_complete == 0 ]]; then
    if [[ -f deps/dist_linux/lib/libx264.a && -f deps/dist_linux/lib/libva.a && -d deps/ffmpeg ]]; then
        # x264 and libva were installed successfully; resume FFmpeg directly.
        (cd deps
         export DIST="$akimbo_build/deps/dist_linux" NPROCS=1
         export FFMPEG_CFLAGS="-I$DIST/include" FFMPEG_LIBRARY_PATH="-L$DIST/lib"
         export FFMPEG_EXTRA_ARGS='--enable-nvenc --enable-ffnvcodec --enable-cuda-llvm --enable-vaapi --enable-libdrm --enable-xlib'
         bash ffmpeg.sh)
    else
        (cd deps && DIST="$akimbo_build/deps/dist_linux" CARGO_CFG_TARGET_OS=linux bash build.sh)
    fi
fi
cargo build --locked --release
install -m 0755 target/release/weylus "$akimbo_data/bin/weylus"
printf '%s\n' "$akimbo_commit" > "$akimbo_data/bin/weylus.commit"
