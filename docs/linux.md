# Booting Linux 🐧

How to boot Linux on the host, type at its shell from Python, share a directory with it, and find out why when it does not boot.

🧦 The kernel is a stock one: Linux's own `defconfig` for RISC-V, with nothing of socpuppet's in it. It runs in supervisor mode on [OpenSBI](boards.md#booting-opensbi), which the host boots the way a server does, and it finds its hardware in the devicetree the host writes. Its root filesystem is [Alpine's](https://alpinelinux.org) mini root, a real distribution's busybox and musl, with one file of ours laid over it.

🎭 Every device Linux talks to is a [virtio stand-in](boards.md#with-the-virtio-slots), a simplified model of the kind a virtual machine offers, which every Linux has drivers for: its console is the virtio console, its root is the virtio disk. The real blocks take the stand-ins' places one at a time, after this ([roadmap.md](roadmap.md)).

## The kernel and its root

```sh
uv run firmware/build.py linux
```

This fetches Linux 6.18.57 from kernel.org and Alpine's mini root, checks both against the SHA-256 pinned in `firmware/versions.toml`, and builds with the Zephyr SDK's LLVM, which the other firmware parts use too. It leaves four files in `build/firmware`:

| File | What it is |
|---|---|
| `linux.bin` | The kernel as the flat `Image` that OpenSBI's `fw_jump` jumps to, 26 MiB |
| `linux.elf` | The same kernel as `vmlinux`, with its symbols, for a debugger |
| `linux.map` | `System.map`, every symbol's address |
| `rootfs.ext4` | Alpine's mini root as an ext4 image, 32 MiB, with `firmware/rootfs/etc/inittab` over Alpine's |

The kernel is the biggest thing built here, so the first build takes a while; CI keeps its images until a pin changes. The kernel's own tree and build are in `build/firmware/<machine>`, with the toolchains. On a Mac the `linux` part builds in the devcontainer's image by itself, with that folder a Docker volume, since the kernel's tree has files whose names differ only in their case ([development.md](development.md)). `firmware/rootfs` is shaped as the guest's own tree: a file put there is in the root at the next build.

## A first boot

The quick way: Python puts `fw_jump`, the kernel and the devicetree in RAM where `fw_jump` expects them, and the root filesystem on the virtio disk.

```python
import re

import socpuppet as sp
from socpuppet import devicetree, opensbi
from socpuppet.boards.boot import ROM_BASE, from_rom
from socpuppet.boards.host import RAM_BASE, host
from socpuppet.boards.virtio import Virtio

root = open("build/firmware/rootfs.ext4", "rb").read()
board = host(boot=from_rom, sbi=True, virtio=Virtio(blocks=len(root) // 512))
layout = opensbi.lay_out(
    open("build/firmware/fw_jump.bin", "rb").read(),
    open("build/firmware/linux.bin", "rb").read(),
    devicetree.compile(
        board.platform.devicetree(
            dialect="linux",
            model="socpuppet host",
            bootargs="console=hvc0 earlycon=sbi root=/dev/vda rw",
        )
    ),
    ram=RAM_BASE,
)
board.platform.build()
board.virtio.blk.load(root)
opensbi.load(board.platform, layout, rom=ROM_BASE, via=board.cpu.socket)

console = board.virtio.console
prompt = re.compile(r"socpuppet:\S+# $")
board.platform.run_until(
    lambda: prompt.search(console.output), timeout=sp.ms(400_000)
)
said = len(console.output)
console.write("uname -a\n")
board.platform.run_until(
    lambda: prompt.search(console.output[said:]), timeout=sp.ms(10_000)
)
print(console.output[said:])
```

```text
uname -a
Linux socpuppet 6.18.57 #1 SMP Sun Oct 18 08:03:06 PDT 2026 riscv64 Linux
socpuppet:~#
```

Run it with `PYTHONPATH=python uv run python linux_hello.py` from the checkout, and `SOCPUPPET_CPU=qbox_cpu` in front for QBox's hart, if your build has it ([qbox-cpu.md](models/qbox-cpu.md)).

- **The command line** is the devicetree's `bootargs`. `console=hvc0` makes the virtio console Linux's console; `earlycon=sbi` sends its first words through OpenSBI's console on the 16550, in `board.uart.output`, until the virtio console is up; `root=/dev/vda rw` is the virtio disk.
- **The prompt comes at 208 s of the CPU's time**: 6 s on the wall on QBox's hart and 75 s on the interpreter. Most of it is the stock kernel's own start-up, the initialisation of everything `defconfig` builds in, with the tracing subsystem's tens of seconds among it. 64 MiB of RAM is enough.
- 🧵 **Type at it** with `console.write`, and Enter is `"\n"`. `poweroff` switches the host off through the system controller, which the kernel's `syscon-poweroff` driver writes.
- **Both harts boot it**, with no change to either. `tests/python/test_m20_exit.py` is the exit test, and `tests/python/linux_shell.py` has the helpers it uses, `a_host_with_linux` and `type_and_wait_for_the_prompt`, which are the way to start.

## The virtio cast under Linux

Each device in the host's virtio slots meets its Linux driver, all of them from `defconfig` unchanged:

| Device | Linux's driver | What the exit test does with it |
|---|---|---|
| [Console](models/virtio-console.md) | `virtio_console`, as `hvc0` | the shell's console: Python types, Linux answers |
| [Disk](models/virtio-blk.md) | `virtio_blk`, as `/dev/vda` | the root filesystem, mounted read-write |
| [Entropy source](models/virtio-rng.md) | `virtio_rng`, as `/dev/hwrng` | reads 16 bytes, which are in the device's seeded stream |
| [Network card](models/virtio-net.md) | `virtio_net`, as `eth0` | given `192.0.2.1`, it answers Python's ARP request and then its ping |
| [Shared directory](models/virtio-9p.md) | `9pnet_virtio` and `9p` | mounted at `/mnt`: Linux reads Python's file and writes one Python reads back |

The shared directory is a directory of this machine, given as `Virtio(share="/some/directory")`, and Linux mounts it by its tag:

```sh
mount -t 9p -o trans=virtio,version=9p2000.L socpuppet /mnt
```

🎓 Linux speaks 9P2000.L to it, the dialect of Plan 9's file protocol that Linux's client speaks, and 🧵 Python serves it with `socpuppet.ninep`. ⚠️ Linux may change anything in the directory, and nothing outside it.

## The server's way, through UEFI

A server does not jump straight to its kernel: its UEFI firmware finds the kernel on a disk and starts it. The kernel's `Image` is a UEFI program too, by the EFI stub built into it, so the same file serves both ways.

- **The disk is cut up as a server's**: a GUID partition table with an EFI system partition, FAT, holding the kernel as `EFI/BOOT/BOOTRISCV64.EFI`, where UEFI's boot manager looks on a disk it has no entry for, and the root filesystem in the second partition. `tests/python/gpt_image.py` and `fat_image.py` make it; `linux_shell.a_disk_as_a_servers` puts them together.
- **The command line** is still the devicetree's, `root=/dev/vda2` this time: the boot manager gives the stub none, and the stub then leaves `bootargs` as they are.
- **It needs more RAM**: UEFI and the kernel together want more than 128 MiB, and the tests give 192.
- **It is on demand**: the prompt comes at 318 s of the CPU's time, 9 s on the wall on QBox and two minutes on the interpreter, so the tests run only when asked, the quick way and from the flash: `SOCPUPPET_ON_DEMAND=1 uv run pytest tests/python/test_m20_exit.py`.
- ⚠️ **The flash cannot hold the kernel**: it is 16 MiB, with the IO manager's image at its end, and the kernel is 26 MiB. From the flash, the ROM starts OpenSBI and UEFI, and UEFI finds the kernel on the disk, as a server's would.

## When it does not boot

A kernel that stops saying anything has stopped somewhere, and these find where, in the order to reach for them:

1. **Read both consoles.** `earlycon=sbi` puts everything the kernel says before its own console is up on `board.uart.output`. Silence after the early lines usually means the virtio console has not come up; `keep_bootcon` on the command line keeps the early console going, to read what the driver said.
2. **A debugger, with the kernel's symbols.** Give the host a `gdb_port` and attach GDB with `linux.elf`, as [boot-your-firmware.md](boot-your-firmware.md) shows for Zephyr: `break start_kernel`, `continue`, then `bt` where it stops. Both harts' servers read the kernel's virtual addresses, so its symbols work as they are. `tests/python/test_gdb.py` breaks at `start_kernel` and reads `linux_banner`. ⚠️ On the DBT-RISE CPU, take a breakpoint away before continuing from it ([upstream.md](upstream.md)).
3. **The other hart.** A kernel that boots on one hart and not on the other has said which side the fault is on.
4. **An instruction trace**, on QBox's hart: QEMU logs every instruction it runs when asked through the debugger, and `socpuppet.qemu_trace` reads the addresses out ([qbox-cpu.md](models/qbox-cpu.md)). Switch it on near the trouble: the whole boot is billions of instructions.

The first boot needed only the first two. The kernel went quiet in its virtio driver, and the debugger had the reason within a minute: a register of the virtio transport that was in the stand-in's map and not in its model, which no other driver had read. 😄 Linux had asked a question nobody else had thought to ask, which is what Linux is for here.
