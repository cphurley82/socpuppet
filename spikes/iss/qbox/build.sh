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

if [[ ! -d /qbox/src/.git ]]; then
  git clone --quiet https://github.com/qualcomm/qbox /qbox/src
fi
git -C /qbox/src -c advice.detachedHead=false checkout --quiet "${qbox_commit}"

cd /qbox/src
# QBox's own preset, with QEMU built for the two RISC-V word sizes only.
cmake --preset gcc -DLIBQEMU_TARGETS="riscv64;riscv32"
time cmake --build build --parallel "${jobs}"
du -sh build | sed 's/^/build tree: /'
