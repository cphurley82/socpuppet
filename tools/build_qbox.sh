#!/usr/bin/env bash
# Builds QBox, Qualcomm's QEMU in SystemC, for socpuppet's qbox_cpu, and
# installs it where `cmake --preset qbox` looks for it:
#
#   uv run tools/build_qbox.sh                 # into build/qbox/install
#   uv run tools/build_qbox.sh --root DIR --jobs N
#
# QEMU is GPL-2.0, so it is never part of the wheel: whoever wants the second
# hart builds it here, from source. It takes about five minutes on 24 threads
# the first time, and its tree is about 3 GB. `uv run` puts uv's CMake and
# Ninja on the path. docs/setup.md lists the packages it needs.
#
# QBox is pinned, and every change made to it, or to the QEMU it fetches, is
# a patch in cmake/patches/ with an entry in docs/upstream.md. A second run
# builds again what changed and applies nothing twice.
set -euo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
patches="$repository/cmake/patches"
qbox_commit=4d63017c88a147839d49028d0c60666d691460cc # 2026-09-24

usage() {
  echo "usage: tools/build_qbox.sh [--root DIR] [--jobs N]" >&2
  exit 2
}

root="$repository/build/qbox"
jobs="$(getconf _NPROCESSORS_ONLN 2> /dev/null || echo 4)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) [[ $# -ge 2 ]] || usage; root="$2"; shift 2 ;;
    --jobs) [[ $# -ge 2 ]] || usage; jobs="$2"; shift 2 ;;
    *) echo "build_qbox.sh: unknown option $1" >&2; usage ;;
  esac
done
mkdir -p "$root"
root="$(cd "$root" && pwd)"

# What QBox's build stops without, and the Ubuntu package each comes in.
missing=()
for tool in git:git cmake:cmake ninja:ninja-build pkg-config:pkg-config \
  meson:meson bison:bison flex:flex; do
  command -v "${tool%%:*}" > /dev/null 2>&1 || missing+=("${tool#*:}")
done
if command -v pkg-config > /dev/null 2>&1; then
  for library in glib-2.0:libglib2.0-dev pixman-1:libpixman-1-dev \
    libzip:libzip-dev libelf:libelf-dev; do
    pkg-config --exists "${library%%:*}" || missing+=("${library#*:}")
  done
fi
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "build_qbox.sh: QBox cannot be built without ${missing[*]}." >&2
  echo "On Ubuntu: sudo apt install ${missing[*]}" >&2
  echo "docs/setup.md lists every package QBox needs." >&2
  exit 1
fi

# Applies a patch unless it is there already, and stops if it is neither.
apply() {
  local tree="$1" patch="$2"
  if git -C "$tree" apply --check "$patch" 2> /dev/null; then
    git -C "$tree" apply "$patch"
    echo "  patched: $(basename "$patch")"
  elif ! git -C "$tree" apply --reverse --check "$patch" 2> /dev/null; then
    echo "build_qbox.sh: $(basename "$patch") does not apply to $tree." >&2
    echo "Delete $root and run this again." >&2
    exit 1
  fi
}

start=$(date +%s)
source="$root/src"
if [[ ! -d "$source/.git" ]]; then
  git clone --quiet https://github.com/qualcomm/qbox "$source"
fi
if [[ "$(git -C "$source" rev-parse HEAD)" != "$qbox_commit" ]]; then
  git -C "$source" fetch --quiet origin "$qbox_commit"
  git -C "$source" checkout --quiet --force "$qbox_commit"
fi
echo "🧦 QBox at ${qbox_commit:0:8}, in $source"
for patch in "$patches"/qbox-*.patch; do
  apply "$source" "$patch"
done

# RISC-V's 64-bit QEMU only. C++20, because SystemC only links with code
# built to the same standard as itself, and socpuppet is C++20. No virgl and
# no virCL: QEMU's bundled virclrenderer does not compile against glibc
# 2.42's C11 threads, and nothing here draws.
build="$root/build"
cmake -S "$source" -B "$build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$root/install" \
  -DCPM_DOWNLOAD_ALL=ON \
  -DLIBQEMU_TARGETS=riscv64 \
  -DCMAKE_CXX_STANDARD=20 \
  -DGS_ENABLE_VIRGLRENDERER=OFF \
  -DGS_ENABLE_VIRCLRENDERER=OFF
# QEMU is fetched while QBox is configured, and built after. Its patches go
# in between.
for patch in "$patches"/libqemu-*.patch; do
  [[ -e "$patch" ]] || continue
  apply "$build/_deps/libqemu-src" "$patch"
done
cmake --build "$build" --parallel "$jobs"
cmake --install "$build" > "$root/install.log"

echo "✅ QBox is installed in $root/install, in $(($(date +%s) - start)) s."
if [[ "$root" == "$repository/build/qbox" ]]; then
  echo "Next: uv run cmake --preset qbox"
else
  echo "Next: uv run cmake --preset qbox -DSOCPUPPET_QBOX_DIR=$root/install"
fi
