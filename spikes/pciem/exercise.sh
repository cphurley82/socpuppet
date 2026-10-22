#!/bin/sh
# Puts each of the puppet's drives on this machine's bus in turn, and has
# its Linux use it as a disk: a 4 KiB write read back, mkfs.ext4, mount, a
# file written, unmount, mount again and compare, e2fsck. Each step is
# timed against the driver's patience (30 s a command).
#
#   sudo spikes/pciem/exercise.sh [behavioral] [stand-in] [zephyr]
#
# Root, for the block device and mount; the drive itself runs as the user
# who ran sudo. pciem.ko has to be loaded (README.md here). The drive is
# found by where it is, under pciem's bus, and never by name: the machine's
# own NVMe drives are nvme0 and nvme1 here, and nothing else is touched.
set -eu

repo=$(cd "$(dirname "$0")/../.." && pwd)
host="$repo/build/dev/spikes/pciem/spike_pciem_host"
board="$repo/build/pciem-ssd.board"
logs="$repo/build/pciem-run"
user=${SUDO_USER:?run this with sudo}
[ "$(id -u)" -eq 0 ] || { echo "run this with sudo" >&2; exit 1; }
[ -c /dev/pciem ] || { echo "no /dev/pciem: load pciem.ko first" >&2; exit 1; }
sudo -u "$user" mkdir -p "$logs"

now() { date +%s.%N; }
since() { echo "$(now) $1" | awk '{printf "%.3f s", $1 - $2}'; }

# The namespace of the one NVMe controller on pciem's bus, or nothing.
puppet() {
  for controller in /sys/class/nvme/nvme*; do
    case $(readlink -f "$controller/device") in
      */pciem*) ;;
      *) continue ;;
    esac
    for namespace in "$controller"/nvme*n1; do
      [ -e "$namespace" ] && echo "/dev/${namespace##*/}"
    done
  done
}

step() {
  label=$1
  shift
  start=$(now)
  if timeout 600 "$@" >"$logs/step.out" 2>&1; then
    echo "  ✅ $label: $(since "$start")"
  else
    echo "  ❌ $label: failed after $(since "$start")"
    sed 's/^/     /' "$logs/step.out" | tail -5
    return 1
  fi
}

# Has the driver reset the controller (it deletes the I/O queues, clears
# CC.EN and sets it again) and waits for it to be live again.
reset() {
  echo 1 >"/sys/class/nvme/$1/reset_controller"
  for _ in $(seq 1200); do
    [ "$(cat "/sys/class/nvme/$1/state")" = live ] && return 0
    sleep 0.1
  done
  return 1
}

exercise() {
  drive=$1
  echo "🧦 $drive"
  case $drive in
    zephyr) extra="--board $board" ;;
    behavioral) extra="--least-timeout 1" ;;
    *) extra="" ;;
  esac
  since_boot=$(date '+%Y-%m-%d %H:%M:%S')
  # The log is root's until the end, when it is handed back.
  # shellcheck disable=SC2086,SC2024
  sudo -u "$user" "$host" "$drive" --log $extra >"$logs/$drive.log" 2>&1 &
  pid=$!
  start=$(now)
  device=""
  for _ in $(seq 1200); do
    device=$(puppet)
    [ -n "$device" ] && [ -b "$device" ] && break
    sleep 0.1
  done
  if [ -z "$device" ]; then
    echo "  ❌ no drive appeared on pciem's bus in 120 s"
    kill -INT "$pid"; wait "$pid" || true
    return 1
  fi
  echo "  ✅ $device appeared: $(since "$start"), $(($(cat "/sys/block/${device#/dev/}/size") / 2048)) MiB"

  mnt=$(mktemp -d)
  pattern=$(mktemp)
  head -c 4096 /dev/urandom >"$pattern"
  head -c 1048576 /dev/urandom >"$mnt.file"
  ok=true
  step "write 4 KiB, direct" dd if="$pattern" of="$device" bs=4096 seek=256 count=1 oflag=direct conv=fsync || ok=false
  step "read it back, direct" dd if="$device" of="$pattern.back" bs=4096 skip=256 count=1 iflag=direct || ok=false
  step "the same bytes" cmp "$pattern" "$pattern.back" || ok=false
  $ok && step "mkfs.ext4" mkfs.ext4 -F -q "$device" || ok=false
  $ok && step "mount" mount "$device" "$mnt" || ok=false
  $ok && step "write 1 MiB and spam" sh -c "cp '$mnt.file' '$mnt/eggs' && echo spam >'$mnt/spam' && sync" || ok=false
  $ok && step "umount" umount "$mnt" || ok=false
  $ok && step "mount again" mount -o ro "$device" "$mnt" || ok=false
  $ok && step "the file came back" sh -c "cmp '$mnt.file' '$mnt/eggs' && grep -q spam '$mnt/spam'" || ok=false
  $ok && step "umount again" umount "$mnt" || ok=false
  $ok && step "e2fsck -fn" e2fsck -fn "$device" || ok=false
  controller=${device#/dev/}
  controller=${controller%n1}
  function=$(basename "$(readlink -f "/sys/class/nvme/$controller/device")")
  $ok && step "reset the controller" reset "$controller" || ok=false
  $ok && step "mount after the reset" mount -o ro "$device" "$mnt" || ok=false
  $ok && step "the file survived it" sh -c "cmp '$mnt.file' '$mnt/eggs'" || ok=false
  $ok && step "umount" umount "$mnt" || ok=false
  # Unbinding shuts the controller down (CC.SHN) and deletes its queues.
  $ok && step "unbind the driver" sh -c "echo $function >/sys/bus/pci/drivers/nvme/unbind" || ok=false
  mountpoint -q "$mnt" && umount "$mnt"
  rm -rf "$mnt" "$mnt.file" "$pattern" "$pattern.back"

  kill -INT "$pid"
  wait "$pid" || true
  tail -2 "$logs/$drive.log" | sed 's/^/  /'
  journalctl -k --no-pager --since "$since_boot" | grep -E "nvme|pciem.*(error|fail)" \
    | grep -vE "poisoned|restored" | cut -c17- >"$logs/$drive.kernel.log" || true
  echo "  the kernel said, of nvme: $(grep -cE 'nvme' "$logs/$drive.kernel.log") lines, in $logs/$drive.kernel.log"
  sleep 2
}

[ $# -gt 0 ] || set -- behavioral stand-in zephyr
for drive in "$@"; do
  exercise "$drive" || true
done
chown -R "$user" "$logs"
