#!/usr/bin/env bash
# Question 4 of M14's boot spike: does Zephyr build for a host with two
# APLICs, a SiFive watchdog that interrupts through the second, and a
# system controller?
#
# It builds three images for `socpuppet_host` against a copy of
# socpuppet's Zephyr module with the files in overlay/ laid over it: a
# devicetree written by hand, two bindings, and the `irq_enable` glue
# taught that there is more than one APLIC. Nothing is simulated. The
# toolchain and Zephyr are the ones firmware/build.sh has already fetched.
#
#   spikes/boot/zephyr/build.sh     (leaves build/spikes/boot/zephyr/)
set -euo pipefail

repository=$(cd "$(dirname "$0")/../../.." && pwd)
if [[ "$(uname -s)-$(uname -m)" == Darwin-x86_64 ]]; then
  exec docker run --rm --volume "${repository}:/workspace" \
    --workdir /workspace socpuppet-dev spikes/boot/zephyr/build.sh
fi

firmware=${repository}/build/firmware
out=${repository}/build/spikes/boot/zephyr
module=${out}/module
rm -rf "${module}"
mkdir -p "${out}"
cp -R "${repository}/python/socpuppet/zephyr_module" "${module}"
cp -R "${repository}/spikes/boot/zephyr/overlay/." "${module}/"

export ZEPHYR_BASE=${firmware}/zephyr
export ZEPHYR_TOOLCHAIN_VARIANT=zephyr
export ZEPHYR_SDK_INSTALL_DIR=${firmware}/zephyr-sdk-1.0.1
export PATH=${firmware}/venv/bin:${PATH}

for application in samples/hello_world samples/subsys/shell/shell_module \
  samples/drivers/watchdog; do
  name=$(basename "${application}")
  build=${out}/build_${name}
  echo "Building ${name}"
  cmake -S "${ZEPHYR_BASE}/${application}" -B "${build}" -G Ninja \
    -DBOARD=socpuppet_host -DZEPHYR_EXTRA_MODULES="${module}" \
    -DUSER_CACHE_DIR="${out}/cache" > "${build}.log" 2>&1 ||
    { tail -n 40 "${build}.log" >&2; exit 1; }
  cmake --build "${build}" >> "${build}.log" 2>&1 ||
    { tail -n 60 "${build}.log" >&2; exit 1; }
  cp "${build}/zephyr/zephyr.elf" "${out}/${name}.elf"
  grep --extended-regexp "CONFIG_(WDT_SIFIVE|RISCV_APLIC|RISCV_IMSIC|SYSCON)=" \
    "${build}/zephyr/.config" | tr '\n' ' '
  echo
done
