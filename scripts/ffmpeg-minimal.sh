#!/usr/bin/env bash
# Weylus only needs H.264 encoding, fragmented MP4, and video scaling/upload.
# Avoid compiling thousands of unrelated audio/video decoders on small hosts.
set -euo pipefail
cd ffmpeg
PKG_CONFIG_PATH="$DIST/lib/pkgconfig" ./configure \
  --prefix="$DIST" --disable-debug --disable-doc --enable-static --disable-shared \
  --enable-pic --enable-stripping --disable-programs --enable-gpl --enable-libx264 \
  --disable-autodetect --disable-everything \
  --enable-encoder=libx264,h264_vaapi,h264_nvenc --enable-muxer=mp4 \
  --enable-protocol=file \
  --enable-filter=buffer,buffersink,scale,format,hwupload,hwupload_cuda,scale_cuda,scale_vaapi \
  --extra-cflags="$FFMPEG_CFLAGS" --extra-ldflags="$FFMPEG_LIBRARY_PATH" \
  $FFMPEG_EXTRA_ARGS
make -j"$NPROCS"
make install
