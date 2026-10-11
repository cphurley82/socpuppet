#!/usr/bin/env bash
# Builds QBox on its own, for Hexagon only, the way spikes/iss/qbox/build.sh
# does for RISC-V. Run inside the image built from the Dockerfile next to
# this script:
#
#   docker build -t socpuppet-qbox-hexagon spikes/npu/hexagon
#   docker run --rm -v socpuppet-qbox-hexagon:/qbox -v "$PWD:/workspace" \
#     socpuppet-qbox-hexagon /workspace/spikes/npu/hexagon/build.sh
#
# Everything ends up in /qbox (a volume, so that a second run picks up
# where the first left off). The build is C++20 from the start, which is
# what socpuppet's headers need, and takes the ISS spike's two patches.
set -euo pipefail

# The ISS spike's commit, b745c62, pins a libqemu tag that is not on
# GitHub (libqemu-v11.0.50-v0.1, see docs/npu-spike.md). This is the last
# commit before that, and its tag is there.
qbox_commit=4d63017c88a147839d49028d0c60666d691460cc # 2026-09-24
jobs=${JOBS:-4}

if [[ ! -d /qbox/src/.git ]]; then
  git clone --quiet https://github.com/qualcomm/qbox /qbox/src
fi
# The commit is not on a branch any more, so a clone does not bring it.
git -C /qbox/src fetch --quiet origin "${qbox_commit}"
git -C /qbox/src -c advice.detachedHead=false checkout --quiet "${qbox_commit}"

cd /qbox/src
# The ISS spike's two source patches for C++20 (see spikes/iss/qbox/build.sh).
if [[ -f systemc-components/common/include/semaphore.h ]]; then
  git mv systemc-components/common/include/semaphore.h \
    systemc-components/common/include/gs_semaphore.h
  sed -i 's|#include <semaphore.h>|#include <gs_semaphore.h>|' \
    systemc-components/common/include/qkmulti-rolling.h
fi
sed -i 's|FactoryMaker<T, U...>(const char\* _t)|FactoryMaker(const char* _t)|' \
  systemc-components/common/include/cciutils.h
sed -i 's|TargetSignalSocketProxy<bool>(TargetSignalSocket<bool>& parent)|TargetSignalSocketProxy(TargetSignalSocket<bool>\& parent)|' \
  systemc-components/common/include/ports/target-signal-socket.h

# Source patch 3, the NPU spike's own. The Hexagon components hand a string
# built at run time ("..." + dsp_arch) to SCP_FATAL, which is fmt::format
# underneath, and in C++20 fmt checks its format string at compile time
# and refuses one it cannot see. A format string and an argument is what
# it wants (see docs/upstream.md, under QBox).
sed -i 's|("Unrecognized Architecture Revision: " + dsp_arch)|("Unrecognized Architecture Revision: {}", dsp_arch)|' \
  qemu-components/cpu_hexagon/include/hexagon.h \
  qemu-components/hexagon_globalreg/include/hexagon_globalreg.h

cmake --preset gcc -DLIBQEMU_TARGETS="hexagon" -DCMAKE_CXX_STANDARD=20
time cmake --build build --parallel "${jobs}"
cmake --install build > /qbox/install.log
# QBox takes its QEMU from the head of a branch, not a commit. Say which.
git -C build/_deps/libqemu-src rev-parse HEAD | sed 's/^/qemu commit: /'
du -sh build | sed 's/^/build tree: /'
