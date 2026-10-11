#!/usr/bin/env bash
# Builds the spike's boot ROM for both kinds of CPU, with the Zephyr SDK's
# compiler that firmware/build.sh has already fetched into build/firmware.
# On an Intel Mac that toolchain is a Linux one, so this runs itself in the
# devcontainer's image, as firmware/build.sh does.
#
#   spikes/boot/rom/build.sh        (leaves build/spikes/boot/rom_rv{32,64}.elf)
set -euo pipefail

repository=$(cd "$(dirname "$0")/../../.." && pwd)
if [[ "$(uname -s)-$(uname -m)" == Darwin-x86_64 ]]; then
  exec docker run --rm --volume "${repository}:/workspace" \
    --workdir /workspace socpuppet-dev spikes/boot/rom/build.sh
fi

gcc=${repository}/build/firmware/zephyr-sdk-1.0.1/gnu/riscv64-zephyr-elf/bin/riscv64-zephyr-elf
source=${repository}/spikes/boot/rom
out=${repository}/build/spikes/boot
mkdir -p "${out}"


# name, -march, -mabi, where the UART is, the top of RAM, the flash.
#
# ⚠️ The linker script is given to gcc itself with -T. Handed to the linker
# with -Wl,-T it is ignored without a word: the SDK's gcc is set up for
# picolibc, whose own script it uses unless it sees a -T of its own, and
# the ROM then links at 0x1000_0000 with a stack and a heap it never asked
# for.
build() {
  local name=$1 march=$2 mabi=$3 uart=$4 stack=$5 flash=$6
  "${gcc}-gcc" -march="${march}" -mabi="${mabi}" -mcmodel=medany \
    -Os -Wall -Wextra -Werror -ffreestanding -nostdlib -nostartfiles \
    -DUART_BASE="${uart}" -DSTACK_TOP="${stack}" -DFLASH_BASE="${flash}" \
    -T "${source}/rom.ld" \
    "${source}/start.S" "${source}/main.c" -o "${out}/${name}.elf"
  "${gcc}-objcopy" -O binary "${out}/${name}.elf" "${out}/${name}.bin"
  "${gcc}-readelf" --file-header "${out}/${name}.elf" |
    grep --extended-regexp "Class|Entry point"
  echo "  $(wc -c < "${out}/${name}.bin" | tr -d ' ') bytes in ${name}.bin"
}

build rom_rv64 rv64imac_zicsr lp64 0x10000000 0x84000000 0x20000000
build rom_rv32 rv32imac_zicsr ilp32 0x10000000 0x20040000 0x30000000
