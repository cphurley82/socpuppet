#!/usr/bin/env bash
# Builds the firmware the tests boot. Most of it is Zephyr's own, three
# samples and two of its tests, and three applications are socpuppet's:
#   hello_world       for the stock qemu_riscv64 and qemu_riscv32 boards
#   hello_world       for socpuppet_host, socpuppet_ssd and
#                     socpuppet_iomgr, socpuppet's own boards: the host,
#                     the SSD's controller, and the IO die's manager
#   synchronization   for socpuppet_host
#   shell_module      for socpuppet_host: Zephyr's shell, which is typed
#                     at, and is woken by the console's interrupt
#   disk_access       for socpuppet_host with its SSD: Zephyr's test of its
#                     disk interface, which here drives its NVMe driver
#   iomgr             for socpuppet_iomgr: the IO die's manager firmware,
#                     which is the application in firmware/iomgr
#   ssd               for socpuppet_ssd: the SSD's own firmware, which is
#                     the application in firmware/ssd
#   flash_test        for socpuppet_ssd: Zephyr's test of a flash driver,
#                     which here is the driver for the SSD's NAND. The
#                     application in firmware/flash_test says how to build
#                     it for the board, and adds nothing to it
#   watchdog          for socpuppet_host and socpuppet_ssd: the application
#                     in firmware/watchdog, which asks for a reset and
#                     then stops feeding its watchdog, and says why it
#                     started each time
#
# And three things that are no Zephyr at all. The boot ROM in firmware/rom,
# which is what a CPU that boots from a flash runs first. It is built with
# the same compiler, once for each kind of CPU, as rom_rv32 and rom_rv64.
# And OpenSBI, the machine-mode firmware a RISC-V kernel sits on, built for
# the host as fw_jump, with test_payload, the supervisor-mode program
# OpenSBI ships, for it to jump to. And sbi_payload, a program of ours for
# OpenSBI to jump to instead, in firmware/sbi_payload.
#
#   firmware/build.sh [output directory]    (default: build/firmware)
#
# For each Zephyr image it leaves, in the output directory:
#   <name>_<board>.elf          the image, with symbols
#   <name>_<board>.bin          the same as flat bytes, loaded at the start of RAM
#   <name>_<board>.opcodes.txt  how often each instruction appears in it
# and for the boot ROM, rom_rv32 and rom_rv64, each an .elf and a .bin, as
# are fw_jump, test_payload and sbi_payload.
#
# Everything it downloads (the Zephyr SDK's RISC-V toolchain, OpenSBI,
# Zephyr itself, and a Python with the packages Zephyr's build needs) stays
# in the output directory. A second run reuses what is there.
#
# The Zephyr SDK has no toolchain for an Intel Mac. There the script runs
# itself in the devcontainer's image, which is Linux, and needs Docker for
# that. The images come out the same: they are RISC-V programs, and do not
# care what built them.
set -euo pipefail

# zephyr_version and sdk_version.
# shellcheck source=firmware/versions.sh
source "$(dirname "$0")/versions.sh"
# Each image to build, as "application board [shield]". The application is
# a directory of Zephyr's, or one of this repository's if it starts with
# "firmware/", and the image is named after the last part of it. A shield is Zephyr's word for hardware plugged into a board:
# `socpuppet_host_drive` is the host's SSD and the PCIe link it is on.
images=(
  "samples/hello_world qemu_riscv64"
  "samples/hello_world qemu_riscv32"
  "samples/hello_world socpuppet_host"
  "samples/hello_world socpuppet_ssd"
  "samples/hello_world socpuppet_iomgr"
  "samples/synchronization socpuppet_host"
  "samples/subsys/shell/shell_module socpuppet_host"
  "tests/drivers/disk/disk_access socpuppet_host socpuppet_host_drive"
  "firmware/iomgr socpuppet_iomgr"
  "firmware/ssd socpuppet_ssd"
  "firmware/flash_test socpuppet_ssd"
  "firmware/watchdog socpuppet_host"
  "firmware/watchdog socpuppet_ssd"
)
# socpuppet's boards, shields and drivers are in a Zephyr module that ships
# inside the Python package (`socpuppet zephyr-module` prints where). Here
# it is used straight from the repository.
repository=$(cd "$(dirname "$0")/.." && pwd)
module=${repository}/python/socpuppet/zephyr_module

mkdir -p "${1:-build/firmware}"
out=$(cd "${1:-build/firmware}" && pwd)

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) host=linux-x86_64 ;;
  Linux-aarch64) host=linux-aarch64 ;;
  Darwin-arm64) host=macos-aarch64 ;;
  Darwin-x86_64)
    if ! command -v docker > /dev/null; then
      echo "The Zephyr SDK has no toolchain for an Intel Mac, so this script builds the firmware in a Linux container, and it found no Docker to do that with." >&2
      echo "Install Docker Desktop, start it, and run this again." >&2
      exit 1
    fi
    # The image is the devcontainer's, which is also what CI builds in. It
    # is built the first time, which takes a minute, and kept.
    image=socpuppet-dev
    docker image inspect "${image}" > /dev/null 2>&1 ||
      docker build --tag "${image}" \
        --file "${repository}/.devcontainer/Dockerfile" "${repository}/.devcontainer"
    # The repository is at /workspace in there, and an output directory
    # inside it is at the same place under it as here, so that a path the
    # build writes into an image (a source file's, for a debugger) is good
    # in any container that has the repository at /workspace.
    case ${out} in
      "${repository}"/*) inside=/workspace/${out#"${repository}/"} ;;
      *) inside=/firmware ;;
    esac
    exec docker run --rm \
      --volume "${repository}:/workspace" --volume "${out}:${inside}" \
      --workdir /workspace "${image}" firmware/build.sh "${inside}"
    ;;
  *)
    echo "The Zephyr SDK has no toolchain for this machine ($(uname -s) $(uname -m))." >&2
    echo "Build the firmware on Linux (x86-64 or arm64) or on a Mac." >&2
    exit 1
    ;;
esac

# Downloads one file of the SDK release into the output directory and
# checks it against the release's list of checksums.
fetch_sdk_file() {
  local file=$1
  local release=https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v${sdk_version}
  (
    cd "${out}"
    curl --fail --silent --show-error --location --remote-name "${release}/sha256.sum"
    curl --fail --silent --show-error --location --remote-name "${release}/${file}"
    if command -v sha256sum > /dev/null; then
      grep " ${file}\$" sha256.sum | sha256sum --check --quiet -
    else
      grep " ${file}\$" sha256.sum | shasum --algorithm 256 --check --quiet -
    fi
  )
}

# Says what kind of program an image is, where it starts, and how many
# bytes it is, for the image at <path>.elf and <path>.bin.
report_image() {
  local image=$1
  "${toolchain}/bin/riscv64-zephyr-elf-readelf" --file-header "${image}.elf" |
    grep --extended-regexp "Class|Entry point"
  echo "  $(wc -c < "${image}.bin" | tr -d ' ') bytes in ${image}.bin"
}

# The toolchain: the SDK's small base bundle, plus the one RISC-V compiler,
# which builds for both 32 and 64 bits.
sdk=${out}/zephyr-sdk-${sdk_version}
toolchain=${sdk}/gnu/riscv64-zephyr-elf
if [[ ! -d ${toolchain} ]]; then
  echo "Fetching the Zephyr SDK ${sdk_version} RISC-V toolchain for ${host}"
  bundle=zephyr-sdk-${sdk_version}_${host}_minimal.tar.xz
  fetch_sdk_file "${bundle}"
  tar xf "${out}/${bundle}" -C "${out}"
  rm "${out}/${bundle}"
  compiler=toolchain_gnu_${host}_riscv64-zephyr-elf.tar.xz
  fetch_sdk_file "${compiler}"
  mkdir -p "${sdk}/gnu"
  tar xf "${out}/${compiler}" -C "${sdk}/gnu"
  rm "${out}/${compiler}"
fi

# The SDK's LLVM, for OpenSBI alone. 🎓 OpenSBI runs wherever it is put,
# which it does by being linked as a position-independent executable, and
# the GNU linker above is built for bare-metal programs and cannot make
# one. LLVM's linker can, for any target. It is kept beside the SDK and
# not in it: it is two gigabytes, and what copies or caches the SDK for
# Zephyr (firmware/twister.sh, and CI) would carry it for nothing.
llvm=${out}/llvm-${sdk_version}
if [[ ! -d ${llvm} ]]; then
  echo "Fetching the Zephyr SDK ${sdk_version} LLVM toolchain for ${host}"
  compiler=toolchain_llvm_${host}.tar.xz
  fetch_sdk_file "${compiler}"
  mkdir -p "${llvm}"
  tar xf "${out}/${compiler}" -C "${llvm}" --strip-components=1
  rm "${out}/${compiler}"
fi

# The boot ROM: a program with no operating system and no C library under
# it, linked to run from where a socpuppet CPU has its ROM. It needs the
# compiler and nothing of Zephyr's, so it is built first. It includes the
# register maps the Zephyr module carries, for the system controller and
# for the header of the image it loads.
#
# ⚠️ The linker script is given to gcc itself with -T. Handed to the linker
# with -Wl,-T it is ignored without a word: the SDK's gcc is set up for
# picolibc, whose own script it uses unless it sees a -T of its own.
rom=${repository}/firmware/rom
for each in "rv64 rv64imac_zicsr lp64" "rv32 rv32imac_zicsr ilp32"; do
  read -r kind march mabi <<< "${each}"
  echo "Building the boot ROM for ${kind}"
  image=${out}/rom_${kind}
  "${toolchain}/bin/riscv64-zephyr-elf-gcc" \
    -march="${march}" -mabi="${mabi}" -mcmodel=medany \
    -Os -g -Wall -Wextra -Werror -ffreestanding -nostdlib -nostartfiles \
    -I "${module}/include" -include "${rom}/board_${kind}.h" \
    -T "${rom}/rom.ld" \
    "${rom}/start.S" "${rom}"/*.c -o "${image}.elf"
  "${toolchain}/bin/riscv64-zephyr-elf-objcopy" -O binary "${image}.elf" "${image}.bin"
  report_image "${image}"
done

# OpenSBI, at the release socpuppet is pinned to, for the host, built with
# the SDK's LLVM. It needs nothing of Zephyr's either.
#
# 🎓 `fw_jump` is the build of OpenSBI that jumps to a next stage somebody
# else has put in RAM: on the generic platform, 2 MiB into it, which is
# where Linux wants to be. The generic platform also builds fw_payload,
# which carries its next stage inside it, and test_payload, the payload it
# carries when it is given none; FW_PAYLOAD_OFFSET links test_payload where
# fw_jump jumps. OpenSBI runs wherever it is put, and FW_TEXT_START is only
# where its ELF file says it goes: the start of the host's RAM, so that
# Python can load it there.
#
# ⚠️ The SDK's clang knows which C libraries it has, and refuses flags it
# has none for. OpenSBI links no C library at all, so the refusal is
# turned off.
opensbi=${out}/opensbi
if [[ ! -d ${opensbi} ]]; then
  echo "Fetching OpenSBI ${opensbi_version}"
  git clone --quiet --depth 1 --branch "${opensbi_version}" \
    -c advice.detachedHead=false \
    https://github.com/riscv-software-src/opensbi "${opensbi}"
fi
# What socpuppet changes in OpenSBI, each a patch with its entry in
# docs/upstream.md. They are applied to a clean tree every time, so that a
# patch that changes is the one built.
git -C "${opensbi}" checkout --quiet -- .
for patch in "${repository}"/cmake/patches/opensbi-*.patch; do
  git -C "${opensbi}" apply "${patch}"
done
echo "Building OpenSBI for the host"
make -C "${opensbi}" O="${out}/build_opensbi" \
  LLVM="${llvm}/bin/" CC="${llvm}/bin/clang -Wno-missing-multilib" \
  PLATFORM=generic PLATFORM_RISCV_XLEN=64 PLATFORM_RISCV_ABI=lp64 \
  PLATFORM_RISCV_ISA=rv64imafdc_zicsr_zifencei \
  FW_TEXT_START=0x80000000 FW_PAYLOAD_OFFSET=0x200000 \
  > "${out}/build_opensbi.log" 2>&1 ||
  { tail -n 40 "${out}/build_opensbi.log" >&2; exit 1; }
built=${out}/build_opensbi/platform/generic/firmware
for each in "fw_jump fw_jump" "test_payload payloads/test"; do
  read -r name file <<< "${each}"
  cp "${built}/${file}.elf" "${out}/${name}.elf"
  cp "${built}/${file}.bin" "${out}/${name}.bin"
  report_image "${out}/${name}"
done

# A next stage for OpenSBI of socpuppet's own, in firmware/sbi_payload: a
# program in supervisor mode that makes the calls of SBI's that OpenSBI's
# test_payload does not. It is built as the ROM is, for where fw_jump
# jumps, and finds the system controller where the ROM does.
payload=${repository}/firmware/sbi_payload
echo "Building the payload of ours for OpenSBI"
image=${out}/sbi_payload
"${toolchain}/bin/riscv64-zephyr-elf-gcc" \
  -march=rv64imac_zicsr -mabi=lp64 -mcmodel=medany \
  -Os -g -Wall -Wextra -Werror -ffreestanding -nostdlib -nostartfiles \
  -I "${module}/include" -include "${rom}/board_rv64.h" \
  -T "${payload}/payload.ld" \
  "${payload}/start.S" "${payload}"/*.c -o "${image}.elf"
"${toolchain}/bin/riscv64-zephyr-elf-objcopy" -O binary "${image}.elf" "${image}.bin"
report_image "${image}"

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
# in an environment of their own. The Python itself is uv's, kept in the
# output directory with the rest. An environment only points at its Python,
# and one that pointed outside the output directory would be left pointing
# at nothing when this runs in a container that is thrown away afterwards.
# So an environment whose CMake no longer runs is made again.
venv=${out}/venv
if ! "${venv}/bin/cmake" --version > /dev/null 2>&1; then
  echo "Installing what Zephyr's build needs"
  rm -rf "${venv}"
  UV_PYTHON_INSTALL_DIR=${out}/python \
    uv venv --quiet --python-preference only-managed "${venv}"
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
  case ${application} in
    firmware/*) source=${repository}/${application} ;;
    *) source=${zephyr}/${application} ;;
  esac
  cmake -S "${source}" -B "${build}" -G Ninja \
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
  report_image "${image}"
done
