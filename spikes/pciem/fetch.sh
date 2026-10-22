#!/bin/sh
# Fetches pciem at the commit the spike was run against, and builds its
# kernel module and its NVMe example against the running kernel.
#
#   spikes/pciem/fetch.sh [directory]     (default: build/pciem)
#
# pciem is GPL-2.0-only and is never part of socpuppet: it is downloaded
# into the build tree, as QBox is. Building it needs the running kernel's
# headers (linux-headers-$(uname -r) on Ubuntu) and no root; loading it
# does (README.md here).
set -eu

commit=f80bbb7101e180f3ed8cff3a2136e52a101f336c
dir=${1:-build/pciem}

if [ ! -d "$dir/.git" ]; then
  git clone --quiet https://github.com/cakehonolulu/pciem.git "$dir"
fi
git -C "$dir" fetch --quiet origin "$commit"
git -C "$dir" checkout --quiet "$commit"

# -Werror as pciem's own CI builds it. Its other examples need libraries
# (SDL3) that the NVMe one does not, so only that one is built.
make -C "$dir" modules KCFLAGS=-Werror
make -C "$dir/examples/nvme"
echo "pciem $commit built in $dir: kernel/pciem.ko and examples/nvme/nvme_card"
