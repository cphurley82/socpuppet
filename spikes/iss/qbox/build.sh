#!/usr/bin/env bash
# Builds QBox on its own, with its own build system, for RISC-V only.
# Run inside the image built from the Dockerfile next to this script:
#
#   docker build -t socpuppet-qbox spikes/iss/qbox
#   docker run --rm -v socpuppet-qbox:/qbox -v "$PWD:/workspace" \
#     socpuppet-qbox /workspace/spikes/iss/qbox/build.sh
#
# QBox, QEMU and everything else it downloads end up in /qbox (a volume, so
# that a second run picks up where the first left off).
set -euo pipefail

qbox_commit=b745c62ddfe7a521c2afe7107c0bdae086dd1f53 # 2026-09-30
jobs=${JOBS:-4}
# QBox builds itself as C++17. socpuppet is C++20, and SystemC only links
# with code built to the same standard, so putting the two in one program
# needs QBOX_CXX_STANDARD=20.
standard=${QBOX_CXX_STANDARD:-17}

if [[ ! -d /qbox/src/.git ]]; then
  git clone --quiet https://github.com/qualcomm/qbox /qbox/src
fi
git -C /qbox/src -c advice.detachedHead=false checkout --quiet "${qbox_commit}"

cd /qbox/src
if [[ ${standard} == 20 && -f systemc-components/common/include/semaphore.h ]]; then
  # Source patch 1. QBox has a header called semaphore.h. In C++20 the
  # standard library's <thread> reaches <semaphore>, which includes the C
  # library's <semaphore.h>, and finds QBox's instead. Give QBox's another
  # name.
  git mv systemc-components/common/include/semaphore.h \
    systemc-components/common/include/gs_semaphore.h
  sed -i 's|#include <semaphore.h>|#include <gs_semaphore.h>|' \
    systemc-components/common/include/qkmulti-rolling.h
fi
if [[ ${standard} == 20 ]]; then
  # Source patch 2. Two constructors are declared with their template
  # arguments spelled out, `Name<T>(...)`, which C++20 no longer allows.
  sed -i 's|FactoryMaker<T, U...>(const char\* _t)|FactoryMaker(const char* _t)|' \
    systemc-components/common/include/cciutils.h
  sed -i 's|TargetSignalSocketProxy<bool>(TargetSignalSocket<bool>& parent)|TargetSignalSocketProxy(TargetSignalSocket<bool>\& parent)|' \
    systemc-components/common/include/ports/target-signal-socket.h
fi
# QBox's own preset, with QEMU built for the two RISC-V word sizes only.
cmake --preset gcc -DLIBQEMU_TARGETS="riscv64;riscv32" \
  -DCMAKE_CXX_STANDARD="${standard}"
time cmake --build build --parallel "${jobs}"
du -sh build | sed 's/^/build tree: /'
