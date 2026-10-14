#!/usr/bin/env bash
# Builds QBox for RISC-V, as C++20, into $QBOX_ROOT (default /qbox), for the
# speed spike's QBox rows. It is spikes/iss/qbox/build.sh at the commit
# spikes/npu/hexagon/build.sh builds, which is the last one whose QEMU tag
# is published. QBox does not need Docker: on Ubuntu its packages are the
# ones spikes/iss/qbox/Dockerfile installs, and on a Mac it is built in
# that image (README.md).
set -euo pipefail

root="${QBOX_ROOT:-/qbox}"
qbox_commit=4d63017c88a147839d49028d0c60666d691460cc # 2026-09-24
jobs=${JOBS:-4}
# macOS's sed wants a suffix after -i, GNU's takes the script there.
sedi() { if sed --version > /dev/null 2>&1; then sed -i "$@"; else sed -i "" "$@"; fi; }
preset=gcc
[[ "$(uname -s)" == Darwin ]] && preset=mac

mkdir -p "$root"
if [[ ! -d "$root/src/.git" ]]; then
  git clone --quiet https://github.com/qualcomm/qbox "$root/src"
fi
git -C "$root/src" fetch --quiet origin "${qbox_commit}"
git -C "$root/src" checkout --quiet --force "${qbox_commit}"

cd "$root/src"
# The ISS spike's two source patches for C++20 (spikes/iss/qbox/build.sh).
if [[ -f systemc-components/common/include/semaphore.h ]]; then
  git mv systemc-components/common/include/semaphore.h \
    systemc-components/common/include/gs_semaphore.h
  sedi 's|#include <semaphore.h>|#include <gs_semaphore.h>|' \
    systemc-components/common/include/qkmulti-rolling.h
fi
sedi 's|FactoryMaker<T, U...>(const char\* _t)|FactoryMaker(const char* _t)|' \
  systemc-components/common/include/cciutils.h
sedi 's|TargetSignalSocketProxy<bool>(TargetSignalSocket<bool>& parent)|TargetSignalSocketProxy(TargetSignalSocket<bool>\& parent)|' \
  systemc-components/common/include/ports/target-signal-socket.h

# The NPU spike's third patch (spikes/npu/hexagon/build.sh): the Hexagon
# components hand a string built at run time to SCP_FATAL, which fmt in
# C++20 refuses, and QBox builds them whatever the target.
sedi 's|("Unrecognized Architecture Revision: " + dsp_arch)|("Unrecognized Architecture Revision: {}", dsp_arch)|' \
  qemu-components/cpu_hexagon/include/hexagon.h \
  qemu-components/hexagon_globalreg/include/hexagon_globalreg.h

# No virglrenderer: QEMU's bundled one does not compile against glibc 2.42's
# C11 threads, and Homebrew has none. Nothing here draws.
cmake --preset "$preset" -DLIBQEMU_TARGETS="riscv64" -DCMAKE_CXX_STANDARD=20 \
  -DGS_ENABLE_VIRGLRENDERER=OFF
start=$(date +%s)
cmake --build build --parallel "${jobs}"
echo "build seconds: $(($(date +%s) - start))"
cmake --install build > "$root/install.log"
git -C build/_deps/libqemu-src rev-parse HEAD | sed 's/^/qemu commit: /'
du -sh build | sed 's/^/build tree: /'
