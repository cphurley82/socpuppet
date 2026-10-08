#!/usr/bin/env bash
# Builds the firmware the tests boot. All of it is Zephyr's own, two
# samples and one of its tests:
#   hello_world       for the stock qemu_riscv64 and qemu_riscv32 boards
#   hello_world       for socpuppet_host, socpuppet's own board
#   synchronization   for socpuppet_host
#   disk_access       for socpuppet_host with its SSD: Zephyr's test of its
#                     disk interface, which here drives its NVMe driver
#
#   firmware/build.sh [output directory]    (default: build/firmware)
#
# For each it leaves, in the output directory:
#   <name>_<board>.elf          the image, with symbols
#   <name>_<board>.bin          the same as flat bytes, loaded at the start of RAM
#   <name>_<board>.opcodes.txt  how often each instruction appears in it
#
# Everything it downloads (the Zephyr SDK's RISC-V toolchain, Zephyr itself
# and the Python packages Zephyr's build needs) stays in the output
# directory. A second run reuses what is there.
set -euo pipefail

zephyr_version=v4.4.2
sdk_version=1.0.1
# Each image to build, as "application board [shield]". The application is
# a directory of Zephyr's, and the image is named after the last part of
# it. A shield is Zephyr's word for hardware plugged into a board:
# `socpuppet_host_drive` is the host's SSD and the PCIe link it is on.
images=(
  "samples/hello_world qemu_riscv64"
  "samples/hello_world qemu_riscv32"
  "samples/hello_world socpuppet_host"
  "samples/synchronization socpuppet_host"
  "tests/drivers/disk/disk_access socpuppet_host socpuppet_host_drive"
)
# socpuppet's boards, shields and drivers are in a Zephyr module that ships
# inside the Python package (`socpuppet zephyr-module` prints where). Here
# it is used straight from the repository.
module=$(cd "$(dirname "$0")/../python/socpuppet/zephyr_module" && pwd)

mkdir -p "${1:-build/firmware}"
out=$(cd "${1:-build/firmware}" && pwd)

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) host=linux-x86_64 ;;
  Linux-aarch64) host=linux-aarch64 ;;
  Darwin-arm64) host=macos-aarch64 ;;
  *)
    echo "The Zephyr SDK has no toolchain for this machine ($(uname -s) $(uname -m))." >&2
    echo "Build the firmware on Linux (x86-64 or arm64) or on an Apple silicon Mac." >&2
    exit 1
    ;;
esac

# Downloads one file of the SDK release and checks it against the release's
# list of checksums.
fetch_sdk_file() {
  local file=$1
  local release=https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v${sdk_version}
  curl --fail --silent --show-error --location --remote-name "${release}/${file}"
  if command -v sha256sum > /dev/null; then
    grep " ${file}\$" sha256.sum | sha256sum --check --quiet -
  else
    grep " ${file}\$" sha256.sum | shasum --algorithm 256 --check --quiet -
  fi
}

# The toolchain: the SDK's small base bundle, plus the one RISC-V compiler,
# which builds for both 32 and 64 bits.
sdk=${out}/zephyr-sdk-${sdk_version}
toolchain=${sdk}/gnu/riscv64-zephyr-elf
if [[ ! -d ${toolchain} ]]; then
  echo "Fetching the Zephyr SDK ${sdk_version} RISC-V toolchain for ${host}"
  (
    cd "${out}"
    release=https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v${sdk_version}
    curl --fail --silent --show-error --location --remote-name "${release}/sha256.sum"
    bundle=zephyr-sdk-${sdk_version}_${host}_minimal.tar.xz
    fetch_sdk_file "${bundle}"
    tar xf "${bundle}"
    rm "${bundle}"
    compiler=toolchain_gnu_${host}_riscv64-zephyr-elf.tar.xz
    fetch_sdk_file "${compiler}"
    mkdir -p "${sdk}/gnu"
    tar xf "${compiler}" -C "${sdk}/gnu"
    rm "${compiler}"
  )
fi

# Zephyr itself, at the release socpuppet is pinned to. Nothing built here
# needs any of Zephyr's external modules, so only the one repository is
# fetched.
zephyr=${out}/zephyr
if [[ ! -d ${zephyr} ]]; then
  echo "Fetching Zephyr ${zephyr_version}"
  git clone --quiet --depth 1 --branch "${zephyr_version}" \
    -c advice.detachedHead=false \
    https://github.com/zephyrproject-rtos/zephyr "${zephyr}"
fi

# The Python packages Zephyr's build scripts import, with CMake and Ninja,
# in an environment of their own.
venv=${out}/venv
if [[ ! -x ${venv}/bin/cmake ]]; then
  echo "Installing what Zephyr's build needs"
  uv venv --quiet "${venv}"
  uv pip install --quiet --python "${venv}/bin/python" \
    --requirement "${zephyr}/scripts/requirements-base.txt" cmake ninja
fi

# Zephyr's build expects to be inside a west workspace (west is Zephyr's
# tool for managing its repositories), and at this release it fails without
# one. So the output directory is made a workspace whose only repository is
# Zephyr: nothing more is downloaded.
if [[ ! -d ${out}/.west ]]; then
  (cd "${out}" && "${venv}/bin/west" init --local zephyr > /dev/null)
fi

export ZEPHYR_BASE=${zephyr}
export ZEPHYR_TOOLCHAIN_VARIANT=zephyr
export ZEPHYR_SDK_INSTALL_DIR=${sdk}
export PATH=${venv}/bin:${PATH}

for each in "${images[@]}"; do
  read -r application board shield <<< "${each}"
  name=$(basename "${application}")
  echo "Building ${name} for ${board}${shield:+ with ${shield}}"
  build=${out}/build_${name}_${board}
  cmake -S "${zephyr}/${application}" -B "${build}" -G Ninja \
    -DBOARD="${board}" ${shield:+-DSHIELD="${shield}"} \
    -DCONFIG_BUILD_OUTPUT_BIN=y \
    -DZEPHYR_EXTRA_MODULES="${module}" \
    -DUSER_CACHE_DIR="${out}/cache" > "${build}.log" 2>&1 ||
    { tail -n 40 "${build}.log" >&2; exit 1; }
  cmake --build "${build}" >> "${build}.log" 2>&1 ||
    { tail -n 40 "${build}.log" >&2; exit 1; }

  image=${out}/${name}_${board}
  cp "${build}/zephyr/zephyr.elf" "${image}.elf"
  cp "${build}/zephyr/zephyr.bin" "${image}.bin"
  # A disassembly line is "<address>:", then the instruction's name, then
  # its operands. Without aliases, each is named as the instruction it
  # really is: `ret` shows as the `c.jr` it is encoded as.
  "${toolchain}/bin/riscv64-zephyr-elf-objdump" --disassemble --no-show-raw-insn \
    --disassembler-options=no-aliases "${image}.elf" |
    awk -F '\t' '$1 ~ /:$/ && NF >= 2 { count[$2]++ }
                 END { for (each in count) print count[each], each }' |
    sort --numeric-sort --reverse > "${image}.opcodes.txt"
  "${toolchain}/bin/riscv64-zephyr-elf-readelf" --file-header "${image}.elf" |
    grep --extended-regexp "Class|Entry point"
  echo "  $(wc -c < "${image}.bin" | tr -d ' ') bytes in ${image}.bin"
done
