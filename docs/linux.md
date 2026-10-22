# Booting Linux 🐧

How to boot Linux on the host and type at its shell, yourself or from Python, share a directory with it, and find out why when it does not boot.

🧦 The kernel is a stock one: Linux's own `defconfig` for RISC-V, with nothing of socpuppet's in it. It runs in supervisor mode on [OpenSBI](boards.md#booting-opensbi), which the host boots the way a server does, and it finds its hardware in the devicetree the host writes. Its root filesystem is [Alpine's](https://alpinelinux.org) mini root, a real distribution's busybox and musl, with one file of ours laid over it.

🎭 Every device Linux talks to is a [virtio stand-in](boards.md#with-the-virtio-slots), a simplified model of the kind a virtual machine offers, which every Linux has drivers for: its console is the virtio console, its root is the virtio disk. The real blocks take the stand-ins' places one at a time, after this ([roadmap.md](roadmap.md)).

## The kernel and its root

```sh
uv run firmware/build.py linux
```

This fetches Linux 6.18.57 from kernel.org and Alpine's mini root, checks both against the SHA-256 pinned in `firmware/versions.toml`, and builds with the Zephyr SDK's LLVM, which the other firmware parts use too. It leaves five files in `build/firmware`:

| File | What it is |
|---|---|
| `linux.bin` | The kernel as the flat `Image` that OpenSBI's `fw_jump` jumps to, 26 MiB |
| `linux.elf` | The same kernel as `vmlinux`, with its symbols, for a debugger |
| `linux.map` | `System.map`, every symbol's address |
| `rootfs.ext4` | Alpine's mini root as an ext4 image, 32 MiB, with `firmware/rootfs/etc/inittab` over Alpine's |
| `initramfs.cpio` | An initramfs, 2 MB: Alpine's busybox and musl, and the kernel's two NVMe modules, with `firmware/initramfs/init`, which loads them and mounts the root on the drive |

The kernel is the biggest thing built here, so the first build takes a while; CI keeps its images until a pin changes. The kernel's own tree and build are in `build/firmware/<machine>`, with the toolchains: the tree in a folder named for its version, so a kernel pinned anew is fetched beside the old one, which can then be deleted (on a Mac, where the folder is a Docker volume, from `tools/devcontainer.py bash`). On a Mac the `linux` part builds in the devcontainer's image by itself, with that folder a Docker volume, since the kernel's tree has files whose names differ only in their case ([development.md](development.md)). `firmware/rootfs` and `firmware/initramfs` are shaped as the guest's own trees: a file put there is in the root, or the initramfs, at the next build.

🎓 `defconfig` builds the NVMe driver as modules, `nvme-core.ko` and `nvme.ko`, not into the kernel, as a distro's kernel does. A module lives on a disk, so a kernel whose root is on an NVMe drive cannot load the driver from that drive. An **initramfs** is the way out: a small root filesystem that the kernel unpacks into memory and runs `/init` from before it has any disk. Ours loads the two modules, waits for the drive the command line's `root=` names, mounts it, and hands over to the init on it with `switch_root`. The kernel's own `usr/gen_init_cpio` packs it.

## At its shell yourself

```sh
PYTHONPATH=python uv run python -m socpuppet linux
```

🐧 Linux boots on the host, and your terminal is at its console, as a serial console is: OpenSBI's banner and the kernel's messages scroll by, and then the shell's prompt is yours.

```text
🧦 Booting 🐧 Linux on the host's dbt_rise_cpu. Its shell prompts in a minute or two, after a quiet spell in the middle (in seconds on qbox_cpu). Ctrl-] leaves.

OpenSBI v1.9
   ____                    _____ ____ _____
  / __ \                  / ____|  _ \_   _|
...
[    0.000000] Linux version 6.18.57 ...
...
[  170.898731] Run /sbin/init as init process
socpuppet:~# uname -a
Linux socpuppet 6.18.57 #3 SMP Mon Oct 19 21:10:53 PDT 2026 riscv64 Linux
socpuppet:~# ls /
bin         home        media       proc        sbin        tmp
dev         lib         mnt         root        srv         usr
etc         lost+found  opt         run         sys         var
socpuppet:~#
```

- **Your keys go to Linux as you press them**, as they would down a serial line: Ctrl-C stops what the shell is running, Tab and the arrow keys are busybox's line editing, and what you type before the prompt waits for it. **Ctrl-] leaves**, as in telnet and `virsh console`, and `poweroff` switches the host off; either ends the command. ⚠️ Leaving ends the simulation too: a SystemC kernel cannot be restarted, so the next run boots afresh.
- **The quiet spell** is the stock kernel's own start-up, the initialisation of everything `defconfig` builds in, the tracing subsystem's tens of seconds among it: on the interpreter, a minute on the wall with nothing said, and the prompt at about 80 s. `--cpu qbox_cpu` boots in seconds, on a build with QBox ([qbox-cpu.md](models/qbox-cpu.md)).
- 💡 **While Linux waits, its clock keeps to the wall's.** While the CPU works, the simulation runs as fast as it can; while it sleeps, waiting for a timer or a key, the simulated clock moves as the wall's does. So `sleep 3` takes three seconds, and a prompt nobody is typing at costs your machine almost nothing. 🎓 QEMU does the same with `-icount sleep=on`. The boot ran faster than its own clock, so `uptime` says two minutes where the wall says one and a half.
- **Standard output is the machine's console and nothing else**; socpuppet's own lines go to standard error. So it can be scripted: `printf 'uname -a\npoweroff\n' | socpuppet linux` prints the boot and the answer, and ends when Linux switches the host off.
- ⚠️ **Linux does not know your terminal's size**: 🎭 the virtio console is a stand-in without the size feature, so full-screen programs such as `vi` and `top` assume 80 columns by 24 lines, as on a real serial console. `stty rows 40 cols 120` at the prompt tells it otherwise.
- 🧵 **From Python** it is `socpuppet.interactive.interact`, which puts this process's terminal at any console of any platform: Zephyr's shell on the UART too.

## From Python

`socpuppet.linux.host_with_linux` builds the host with Linux in place, the quick way: Python puts `fw_jump`, the kernel and the devicetree in RAM where `fw_jump` expects them, and the root filesystem on the virtio disk. Then Python waits for the prompt, types, and reads the answer.

```python
import pathlib

import socpuppet as sp
from socpuppet import linux

board = linux.host_with_linux(pathlib.Path("build/firmware"))
console = board.virtio.console
board.platform.run_until(
    lambda: linux.PROMPT.search(console.output), timeout=sp.ms(400_000)
)
said = len(console.output)
console.write("uname -a\n")
board.platform.run_until(
    lambda: linux.PROMPT.search(console.output[said:]), timeout=sp.ms(10_000)
)
print(console.output[said:])
```

```text
uname -a
Linux socpuppet 6.18.57 #3 SMP Mon Oct 19 21:10:53 PDT 2026 riscv64 Linux
socpuppet:~#
```

Run it with `PYTHONPATH=python uv run python linux_hello.py` from the checkout, and `SOCPUPPET_CPU=qbox_cpu` in front for QBox's hart, if your build has it ([qbox-cpu.md](models/qbox-cpu.md)). `socpuppet/linux.py` has the recipe, in a dozen lines.

- **The command line** is the devicetree's `bootargs`, `linux.BOOTARGS`. `console=hvc0` makes the virtio console Linux's console; `earlycon=sbi` sends its first words through OpenSBI's console on the 16550, in `board.uart.output`, until the virtio console is up; `root=/dev/vda rw` is the virtio disk.
- **The prompt comes at 208 s of the CPU's time on QBox's hart**, 6 s on the wall, **and at 171 s on the interpreter**, 75 to 100 s on the wall: the two harts count time a little differently. 64 MiB of RAM is enough.
- 🧵 **Type at it** with `console.write`, and Enter is `"\n"`. `poweroff` switches the host off through the system controller, which the kernel's `syscon-poweroff` driver writes; `socpuppet.boards.host.switched_off(board)` says whether it has.
- **Both harts boot it**, with no change to either. `tests/python/test_m20_exit.py` is the exit test, and `tests/python/linux_shell.py` has the helpers it uses, `a_host_with_linux` and `type_and_wait_for_the_prompt`.

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

## Its root on the drive

The real drive can take 🎭 the virtio disk's place: the SSD with its own Zephyr firmware, across the die-to-die link, on the board with all three firmwares ([boards.md](boards.md)). Linux finds it with its own NVMe driver, behind the root complex, which it reads as a generic ECAM host (`pci-host-ecam-generic`), and the drive's interrupts reach it as MSI-X messages to the IMSIC.

```sh
PYTHONPATH=python uv run python -m socpuppet linux --root drive
```

From Python it is `linux.host_with_linux(firmware, root="drive")`, and `tests/python/test_m24_exit.py` is its test. It needs the IO manager's and the SSD's firmware too, which `uv run firmware/build.py zephyr` builds.

- **The disk is cut up as a server's**: a GUID partition table, `socpuppet.gpt`, with Alpine's root filesystem as its first partition, as big as the drive. `root=/dev/nvme0n1p1` on the command line.
- 🧵 **Python is the factory.** A drive's blocks are not in its NAND as they are on the disk: the SSD's flash translation layer keeps a table of which NAND page holds each, and the table on the NAND itself ([ssd-firmware.md](models/ssd-firmware.md)). `socpuppet.ftl` lays the disk out that way and `nand.load` programs it, as a factory programs a drive before it ships.
- **The initramfs loads the driver.** `defconfig` builds NVMe as modules, so the kernel is given the initramfs (above), whose `/init` loads `nvme-core.ko` and `nvme.ko`, waits for `nvme0n1p1`, and mounts it.
- **It boots in about as long as the virtio root does**: the prompt in 77 s on the wall on the interpreter, with the IO manager's and the SSD's CPUs asleep while they wait.
- The virtio devices stay, for the console and a shared directory; their disk is blank, and Linux sees it as `/dev/vda` beside the drive.
- **The server's way from the drive, on demand**: an EFI system partition on the drive holds UEFI's shell where the boot manager looks (`EFI/BOOT/BOOTRISCV64.EFI`, from `uefi_shell.efi`), a `startup.nsh`, the kernel and the initramfs, and the root is the second partition. UEFI's own NVMe driver reads it; the shell's script starts the kernel with `initrd=\initramfs.cpio` and its command line, which the kernel takes in place of the devicetree's. 🎓 A kernel started through UEFI on RISC-V takes its initramfs from what its loader says, and EDK2's boot manager says nothing, which is why the shell is there. The prompt comes in 2 min 18 s on the wall on the interpreter (`SOCPUPPET_ON_DEMAND=1`).

## The server's way, through UEFI

A server does not jump straight to its kernel: its UEFI firmware finds the kernel on a disk and starts it. The kernel's `Image` is a UEFI program too, by the EFI stub built into it, so the same file serves both ways.

- **The disk is cut up as a server's**: a GUID partition table with an EFI system partition, FAT, holding the kernel as `EFI/BOOT/BOOTRISCV64.EFI`, where UEFI's boot manager looks on a disk it has no entry for, and the root filesystem in the second partition. `socpuppet.gpt` and `tests/python/fat_image.py` make it; `linux_shell.a_disk_as_a_servers` puts them together.
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
