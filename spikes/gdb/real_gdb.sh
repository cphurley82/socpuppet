#!/usr/bin/env bash
# The GDB spike, with the real thing: the Zephyr SDK's GDB attached to each
# of three CPUs at once, where three_debuggers.py speaks the protocol
# itself.
#
#   spikes/gdb/real_gdb.sh [where the simulation is]    (default: 127.0.0.1)
#
# It starts `three_debuggers.py serve` on three ports, then one GDB a CPU,
# all at once. Each GDB loads its firmware's symbols, attaches, says where
# its CPU is, sets a breakpoint on `main`, continues to it, says where and
# when that was, and continues for good. The run ends at the host's
# verdict, which hangs up on the three of them.
#
# ⚠️ The SDK has no GDB for an Intel Mac. There, run this script's GDBs in
# the devcontainer's image, which reaches the Mac as host.docker.internal:
#
#   spikes/gdb/real_gdb.sh docker
set -euo pipefail

repository=$(cd "$(dirname "$0")/../.." && pwd)
firmware=build/firmware
gdb=${firmware}/zephyr-sdk-1.0.1/gnu/riscv64-zephyr-elf/bin/riscv64-zephyr-elf-gdb
where=${1:-127.0.0.1}
out=${SPIKE_OUT:-${repository}/build/spike-gdb}
mkdir -p "${out}"
cd "${repository}"

ports=(3331 3332 3333)
names=(host manager ssd)
images=(disk_access_socpuppet_host.elf iomgr_socpuppet_iomgr.elf ssd_socpuppet_ssd.elf)

uv run python spikes/gdb/three_debuggers.py serve "${ports[@]}" \
  > "${out}/simulation.log" 2>&1 &
simulation=$!
# The ports open when the platform is built.
until grep --quiet "^listening" "${out}/simulation.log"; do
  kill -0 "${simulation}" 2> /dev/null ||
    { cat "${out}/simulation.log"; exit 1; }
  sleep 0.2
done

one_gdb() {
  local name=$1 image=$2 port=$3 target=$4
  # 💡 A GDB whose CPU has not stopped yet gets no answer when it asks for
  # memory, and the host's CPU is held in reset until the manager lets it
  # go. So GDB is told to wait longer than its two seconds.
  "${@:5}" "${gdb}" --batch --nx \
    -ex "set pagination off" \
    -ex "set remotetimeout 60" \
    -ex "file ${firmware}/${image}" \
    -ex "target remote ${target}:${port}" \
    -ex "echo [${name}] attached\n" \
    -ex "info registers pc" \
    -ex "x/2i \$pc" \
    -ex "monitor sysc print_time" \
    -ex "break main" \
    -ex "continue" \
    -ex "echo [${name}] at main\n" \
    -ex "backtrace 3" \
    -ex "monitor sysc print_time" \
    -ex "delete" \
    -ex "continue"
}

for index in 0 1 2; do
  if [[ ${where} == docker ]]; then
    one_gdb "${names[index]}" "${images[index]}" "${ports[index]}" \
      host.docker.internal \
      docker run --rm -v "${repository}":/workspace -w /workspace socpuppet-dev \
      > "${out}/gdb_${names[index]}.log" 2>&1 &
  else
    one_gdb "${names[index]}" "${images[index]}" "${ports[index]}" "${where}" \
      > "${out}/gdb_${names[index]}.log" 2>&1 &
  fi
done

status=0
wait "${simulation}" || status=$?
wait || true
for name in "${names[@]}"; do
  echo "=== ${name}'s GDB"
  cat "${out}/gdb_${name}.log"
done
echo "=== the simulation"
cat "${out}/simulation.log"
exit "${status}"
