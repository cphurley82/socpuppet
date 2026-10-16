#!/usr/bin/env bash
# Runs twister, Zephyr's test runner, on socpuppet's boards, with socpuppet
# as the emulator: Zephyr's own test suites, and ours, built for a board
# and judged by what the board's console prints.
#
#   firmware/twister.sh --suites                       every suite in
#                                                      firmware/twister-suites.txt,
#                                                      on every board
#   firmware/twister.sh --suites -p socpuppet_host     the same, on one board
#   firmware/twister.sh -p socpuppet_ssd -T tests/kernel/sleep -v
#                                                      one suite, by hand
#
# Everything after --suites goes to twister. A -T that is relative is a
# directory of Zephyr's tree, unless it is firmware or python, or under one
# of them: those are this repository's. The verdicts and the logs are left
# in build/twister/out, in a directory for each run of twister: twister.json,
# twister.xml for a CI's test report, twister.log, and each scenario's
# build.log, its handler.log, which is its console, and its
# handler_stderr.log, where `socpuppet run` says how a run ended.
#
# It wants what firmware/build.py leaves in build/firmware (the SDK, Zephyr,
# a venv, the boot ROMs) and a socpuppet built for this machine, which
# `cmake --build --preset dev` leaves importable from python/.
#
# On an Intel Mac it runs itself in the devcontainer's image, as
# firmware/build.py does, since the Zephyr SDK has no toolchain for one.
# There it builds a socpuppet for Linux in build/linux first, and keeps
# Zephyr, the SDK, a venv and twister's build directories on a Docker
# volume, socpuppet-twister: a compiler that reads its headers through
# Docker's file sharing takes ten times as long (docs/twister-spike.md has
# the figures). They are copied to the volume the first time and when
# their versions change, and `docker volume rm socpuppet-twister` throws
# the copy away.
set -euo pipefail

repository=$(cd "$(dirname "$0")/.." && pwd)
# The SDK's version, from the [sdk] table of firmware/versions.toml.
sdk_version=$(sed -n '/^\[sdk\]/,/^\[/s/^version = "\(.*\)"$/\1/p' \
  "${repository}/firmware/versions.toml")
sdk_name=zephyr-sdk-${sdk_version}

if [[ "$(uname -s)-$(uname -m)" == Darwin-x86_64 ]]; then
  command -v docker > /dev/null || {
    echo "On an Intel Mac twister runs in Docker, as firmware/build.py" \
      "does. Install Docker and start it." >&2
    exit 1
  }
  docker image inspect socpuppet-dev > /dev/null 2>&1 ||
    docker build --tag socpuppet-dev \
      --file "${repository}/.devcontainer/Dockerfile" \
      "${repository}/.devcontainer"
  # The venv and its Python are both under build/, as firmware/build.py
  # keeps Zephyr's, so that they outlive the container.
  exec docker run --rm --volume "${repository}:/workspace" \
    --workdir /workspace \
    --volume socpuppet-twister:/twister \
    --env SOCPUPPET_TWISTER_HOME=/twister \
    --env SOCPUPPET_TWISTER_BUILD=build/linux \
    --env UV_PROJECT_ENVIRONMENT=/workspace/build/linux-venv \
    --env UV_PYTHON_INSTALL_DIR=/workspace/build/firmware/python \
    socpuppet-dev firmware/twister.sh "$@"
fi

cd "${repository}"
firmware=${repository}/build/firmware
for each in zephyr venv/bin/python "${sdk_name}" rom_rv32.elf rom_rv64.elf; do
  [[ -e ${firmware}/${each} ]] || {
    echo "There is no ${firmware}/${each}. Run uv run firmware/build.py first," \
      "which fetches Zephyr and its SDK and builds the boot ROMs." >&2
    exit 1
  }
done

# The Python that socpuppet was built for, which runs it.
project_venv=${UV_PROJECT_ENVIRONMENT:-${repository}/.venv}

# In the container, a socpuppet for Linux of the script's own, built again
# each run so that what twister runs is the tree's.
if [[ -n ${SOCPUPPET_TWISTER_BUILD:-} ]]; then
  build=${SOCPUPPET_TWISTER_BUILD}
  # A venv whose Python was in a container that is gone is made again, and
  # the build with it, since its cache names that Python's headers. So is a
  # build whose dependencies were fetched for other patches: configuring
  # again on top of fetched sources would apply the new ones to the old.
  patches=$(cat cmake/Dependencies.cmake cmake/patches/* | cksum)
  if ! "${project_venv}/bin/python" -c '' > /dev/null 2>&1; then
    echo "The Linux venv's Python is gone: making it and ${build} again"
    rm -rf "${project_venv}" "${build}"
  elif [[ -d ${build} && "$(cat "${build}/patches" 2> /dev/null)" != "${patches}" ]]; then
    echo "The dependencies' patches have changed: making ${build} again"
    rm -rf "${build}"
  fi
  uv sync --quiet
  if [[ ! -f ${build}/CMakeCache.txt ]]; then
    echo "Building socpuppet for Linux in ${build}, which takes ten minutes" \
      "the first time"
    uv run cmake -S . -B "${build}" -G Ninja \
      -DCMAKE_BUILD_TYPE=RelWithDebInfo -DSOCPUPPET_DEVELOPER_MODE=ON \
      > /dev/null
    echo "${patches}" > "${build}/patches"
  fi
  uv run cmake --build "${build}" | tail -n 1
fi

# Python's own words are left to be read: a venv that is not there, an
# extension built for another Python and a library that is missing each
# say something different.
PYTHONPATH=${repository}/python "${project_venv}/bin/python" \
  -c 'import socpuppet; socpuppet.Platform' || {
  echo "socpuppet is not built for this machine. Build it first:" \
    "uv sync && uv run cmake --preset dev &&" \
    "uv run cmake --build --preset dev" >&2
  exit 1
}

# What twister imports beyond what a build needs, which
# firmware/build.py puts in Zephyr's venv, and the modules it imports them
# as.
twister_needs=${repository}/firmware/twister-requirements.txt
twister_imports="import psutil, tabulate, natsort, anytree, junitparser"
twister_imports+=", colorama, ply, serial, pytest, packaging, dotenv"

# Where Zephyr, the SDK, the venv and twister's build directories are:
# build/firmware and build/twister, or the volume. A stamp of the two
# versions says whether the volume's copy is the one build/firmware has.
home=${SOCPUPPET_TWISTER_HOME:-}
back=${repository}/build/twister/out
if [[ -n ${home} ]]; then
  stamp="$(git -C "${firmware}/zephyr" describe --tags --always \
    2> /dev/null || echo unknown) ${sdk_name}"
  if [[ ! -f ${home}/stamp || "$(cat "${home}/stamp")" != "${stamp}" ]]; then
    echo "Copying Zephyr and the SDK to the volume, once for each version"
    rm -rf "${home}/zephyr" "${home:?}/${sdk_name}" "${home}/venv" \
      "${home}/.west"
    tar -C "${firmware}" --exclude=zephyr/.git -cf - zephyr "${sdk_name}" |
      tar -C "${home}" -xf -
    (cd "${home}" &&
      "${firmware}/venv/bin/west" init --local zephyr > /dev/null 2>&1)
    echo "${stamp}" > "${home}/stamp"
  fi
  if ! "${home}/venv/bin/python" -c "${twister_imports}" > /dev/null 2>&1; then
    echo "Making the volume's venv"
    rm -rf "${home}/venv"
    UV_PYTHON_INSTALL_DIR=${home}/python uv venv --quiet \
      --python-preference only-managed "${home}/venv"
    uv pip install --quiet --python "${home}/venv/bin/python" \
      --requirement "${home}/zephyr/scripts/requirements-base.txt" \
      --requirement "${twister_needs}" cmake ninja
  fi
  zephyr=${home}/zephyr
  sdk=${home}/${sdk_name}
  venv=${home}/venv
  out=${home}/out
else
  zephyr=${firmware}/zephyr
  sdk=${firmware}/${sdk_name}
  venv=${firmware}/venv
  out=${back}
  "${venv}/bin/python" -c "${twister_imports}" 2> /dev/null ||
    uv pip install --quiet --python "${venv}/bin/python" \
      --requirement "${twister_needs}"
fi

# The emulator, by the name the boards' platform files give it. Twister
# looks for it on its own PATH before it runs anything, and builds a board
# whose emulator it cannot find without ever running it. The tree's own
# socpuppet is not installed anywhere, so it is given a name here.
programs=${repository}/build/twister/bin
mkdir -p "${programs}"
cat > "${programs}/socpuppet" << EOF
#!/bin/sh
PYTHONPATH="${repository}/python" exec "${project_venv}/bin/python" -m socpuppet "\$@"
EOF
chmod +x "${programs}/socpuppet"

export ZEPHYR_BASE=${zephyr}
export ZEPHYR_TOOLCHAIN_VARIANT=zephyr
export ZEPHYR_SDK_INSTALL_DIR=${sdk}
# The same variable tells twister where the boards are and CMake where the
# module is.
export ZEPHYR_EXTRA_MODULES=${repository}/python/socpuppet/zephyr_module
export PATH=${programs}:${venv}/bin:${PATH}
# Where `socpuppet run` finds the boot ROM. Ninja runs it from the image's
# build directory, so the default, build/firmware under where it is run,
# would not do.
export SOCPUPPET_FIRMWARE_DIR=${firmware}
# Zephyr's build uses ccache when it finds one, and it was measured to
# cost more than it saves once the sources are on a local disk.
export USE_CCACHE=0

# A -T that is relative is Zephyr's, unless it is firmware or python, or
# under one of them, where our own suites are.
resolve() {
  case $1 in
    /*) echo "$1" ;;
    firmware | firmware/* | python | python/*) echo "${repository}/$1" ;;
    *) echo "${zephyr}/$1" ;;
  esac
}

# Runs twister once. The first argument names the run, and its output goes
# to a directory of that name.
runs=()
run_twister() {
  local name=$1
  shift
  runs+=("${name}")
  local arguments=()
  while (($#)); do
    case $1 in
      -T | --testsuite-root)
        arguments+=("$1" "$(resolve "$2")")
        shift 2
        ;;
      --testsuite-root=*)
        arguments+=("-T" "$(resolve "${1#--testsuite-root=}")")
        shift
        ;;
      -T*)
        arguments+=("-T" "$(resolve "${1#-T}")")
        shift
        ;;
      *)
        arguments+=("$1")
        shift
        ;;
    esac
  done
  # --clobber-output: the last run's output is replaced, where twister
  # would otherwise keep every run's beside it. It gives way to --no-clean,
  # which builds on the last run's and is for running a failure again.
  "${venv}/bin/python" "${zephyr}/scripts/twister" \
    --outdir "${out}/${name}" --clobber-output --no-detailed-test-id \
    --quarantine-list "${repository}/firmware/twister-quarantine.yaml" \
    "${arguments[@]}"
}

# The verdicts and logs of this command's runs come back from the volume.
# The builds stay.
bring_back() {
  [[ -n ${home} ]] || return 0
  rm -rf "${back}"
  mkdir -p "${back}"
  (cd "${out}" &&
    find "${runs[@]}" \( -name '*.json' -o -name '*.xml' \
      -o -name twister.log -o -name build.log -o -name handler.log \
      -o -name handler_stderr.log \) -print0 |
    tar --null -T - -cf -) | tar -C "${back}" -xf -
}

status=0
if [[ ${1:-} == --suites ]]; then
  shift
  # Every board, unless the command names some.
  boards=(-p socpuppet_host -p socpuppet_ssd -p socpuppet_iomgr)
  for argument in "$@"; do
    case ${argument} in
      -p | --platform | -p* | --platform=*) boards=() ;;
    esac
  done
  # Every suite of the list in one run of twister, which is much quicker
  # than a run each. The suites with flags of their own get a run each, so
  # that a flag such as -K forces nothing but its own suite onto a board.
  # The list is read on a descriptor of its own, so that nothing twister
  # starts finds it on its standard input.
  plain=()
  while read -r suite flags <&3; do
    [[ -n ${suite} && ${suite} != \#* ]] || continue
    if [[ -z ${flags} ]]; then
      plain+=(-T "${suite}")
    else
      echo "=== ${suite} ${flags}"
      # The run is named after its suite: tests-arch-riscv-fatal. The
      # flags are several words.
      # shellcheck disable=SC2086
      run_twister "${suite//\//-}" -T "${suite}" ${flags} \
        ${boards[@]+"${boards[@]}"} "$@" || status=$?
    fi
  done 3< "${repository}/firmware/twister-suites.txt"
  echo "=== the rest of firmware/twister-suites.txt"
  run_twister suites "${plain[@]}" ${boards[@]+"${boards[@]}"} "$@" ||
    status=$?
else
  run_twister one "$@" || status=$?
fi
bring_back
echo "Verdicts and logs: build/twister/out"
exit ${status}
