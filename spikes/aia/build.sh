#!/usr/bin/env bash
# The AIA spike's builds: Zephyr for a socpuppet_host whose devicetree has
# an IMSIC and an APLIC and no PLIC. Nothing is simulated.
#
#   spikes/aia/build.sh
#
# It needs build/firmware, which firmware/build.sh leaves: the toolchain,
# Zephyr and the Python its build wants. The trial module is socpuppet's
# own with this directory's `module/` laid over it, in build/spikes/aia.
set -euo pipefail

repository=$(cd "$(dirname "$0")/../.." && pwd)
if [[ $(uname -s)-$(uname -m) == Darwin-x86_64 ]]; then
  # As firmware/build.sh does: the Zephyr SDK has no toolchain for an Intel
  # Mac, so this runs itself in the devcontainer's image.
  exec docker run --rm --volume "${repository}:/workspace" \
    --workdir /workspace socpuppet-dev spikes/aia/build.sh
fi

firmware=${repository}/build/firmware
out=${repository}/build/spikes/aia
module=${out}/module
rm -rf "${module}"
mkdir -p "${out}"
cp -R "${repository}/python/socpuppet/zephyr_module" "${module}"
cp -R "${repository}/spikes/aia/module/." "${module}/"

export ZEPHYR_BASE=${firmware}/zephyr
export ZEPHYR_TOOLCHAIN_VARIANT=zephyr
export ZEPHYR_SDK_INSTALL_DIR=${firmware}/zephyr-sdk-1.0.1
export PATH=${firmware}/venv/bin:${PATH}

images=(
  "samples/hello_world"
  "tests/drivers/disk/disk_access socpuppet_host_drive"
  "samples/subsys/shell/shell_module"
)
for each in "${images[@]}"; do
  read -r application shield <<< "${each}"
  name=$(basename "${application}")
  build=${out}/build_${name}
  echo "Building ${name}${shield:+ with ${shield}}"
  # From nothing each time. A build directory keeps its configuration, and
  # a change to the board's defconfig does not reach one that exists.
  rm -rf "${build}"
  cmake -S "${ZEPHYR_BASE}/${application}" -B "${build}" -G Ninja \
    -DBOARD=socpuppet_host ${shield:+-DSHIELD="${shield}"} \
    -DZEPHYR_EXTRA_MODULES="${module}" \
    -DUSER_CACHE_DIR="${out}/cache" > "${build}.log" 2>&1 ||
    { tail -n 40 "${build}.log" >&2; exit 1; }
  cmake --build "${build}" >> "${build}.log" 2>&1 ||
    { tail -n 60 "${build}.log" >&2; exit 1; }
  grep --extended-regexp \
    "CONFIG_(RISCV_IMSIC|RISCV_APLIC|RISCV_APLIC_MSI|RISCV_HAS_PLIC|RISCV_ISA_EXT_SMCSRIND|NUM_IRQS|MULTI_LEVEL_INTERRUPTS|SOCPUPPET_AIA_IRQ|UART_INTERRUPT_DRIVEN|FPU)[= ]" \
    "${build}/zephyr/.config" | sed 's/^/  /'
done
