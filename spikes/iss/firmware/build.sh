#!/usr/bin/env bash
# Builds the firmware the ISS spike boots: Zephyr's hello_world sample for
# the stock qemu_riscv64 and qemu_riscv32 boards.
#
#   spikes/iss/firmware/build.sh [output directory]    (default: build/firmware)
#
# For each board it leaves, in the output directory:
#   hello_world_<board>.elf          the image, with symbols
#   hello_world_<board>.bin          the same as flat bytes, loaded at the start of RAM
#   hello_world_<board>.opcodes.txt  how often each instruction appears in it
#
# Everything it downloads (the Zephyr SDK's RISC-V toolchain, Zephyr itself
# and the Python packages Zephyr's build needs) stays in the output
# directory. A second run reuses what is there.
set -euo pipefail

zephyr_version=v4.4.2
sdk_version=1.0.1
boards=(qemu_riscv64 qemu_riscv32)

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

# Zephyr itself, at the release the spike is pinned to. hello_world on these
# boards needs none of Zephyr's external modules, so only the one
# repository is fetched.
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

for board in "${boards[@]}"; do
  echo "Building hello_world for ${board}"
  build=${out}/build_${board}
  cmake -S "${zephyr}/samples/hello_world" -B "${build}" -G Ninja \
    -DBOARD="${board}" -DCONFIG_BUILD_OUTPUT_BIN=y \
    -DUSER_CACHE_DIR="${out}/cache" > "${build}.log" 2>&1 ||
    { tail -n 40 "${build}.log" >&2; exit 1; }
  cmake --build "${build}" >> "${build}.log" 2>&1 ||
    { tail -n 40 "${build}.log" >&2; exit 1; }

  image=${out}/hello_world_${board}
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
