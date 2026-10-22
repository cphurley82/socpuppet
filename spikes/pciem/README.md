# The real-host spike 🚧

Milestone M30 is an experiment: can this machine's own Linux use the puppet's SSD as a drive? The report, with the answers and the recommendation, is [docs/history/real-host-spike.md](../../docs/history/real-host-spike.md).

🎓 [pciem](https://github.com/cakehonolulu/pciem) is a Linux kernel module that lets a program be a PCIe device on the machine's own bus. Its kernel side plays the device's configuration space and its BARs (the base address registers, where a device's registers are), and hands the program the rest: the BAR as shared memory, a ring of the host's writes to it, an ioctl for DMA and one for interrupts. Here the program is the puppet's NVMe drive, and the host is this machine's Linux with its own `nvme` driver.

⚠️ Nothing here is part of socpuppet. It is exploratory code:

- The everyday build, coverage and the wheel never see it. It is built only by the `spike` preset, on Linux, and only where pciem has been fetched.
- Nothing under `src/`, `python/` or `tests/` may include or import it.
- It is not written test-first and does not count towards coverage.
- It includes socpuppet's platform headers and the tests' support headers, so a change there can break it without anything saying so. Run it again before building on it.
- pciem is GPLv2, and the header a program includes to use it is GPL-2.0-only. It is fetched into the build tree, never into the repository, and only `pciem_device.cpp` includes it.

## What is here

| Path | What |
|---|---|
| `fetch.sh` | Clones pciem at the commit the spike ran against into `build/pciem`, and builds its module and its NVMe example. |
| `pciem_device.h`, `.cpp` | The calls to `/dev/pciem`: a device with BAR0 and an MSI-X table, the ring, DMA and interrupts. |
| `pciem_bridge.h` | 🧦 The NVMe function's other side, a SystemC module: the host's writes onto `bar0`, the function's DMA to pciem, a rising line to an interrupt. |
| `rigs.h` | The three drives: 🎭 the behavioral stand-in, the SSD with the C++ firmware stand-in, and the SSD with its CPU running Zephyr's firmware. |
| `describe_ssd.py` | Writes the SSD as Python's `add_ssd_function` describes it, for `rigs.h` to build. |
| `host_spike.cpp` | `spike_pciem_host`, the program that puts a drive on the bus and runs it until Ctrl-C. |
| `exercise.sh` | Has root use each drive as a disk, step by step, timed. |
| `ring_test.cpp`, `pciem_bridge_test.cpp` | What can be tried with no `/dev/pciem`. |

## Running it

Fetch and build pciem (it needs the running kernel's headers, `linux-headers-$(uname -r)` on Ubuntu, and no root), then the spike, and run its tests:

```sh
spikes/pciem/fetch.sh
uv run cmake --preset spike
uv run cmake --build --preset spike --target spike_pciem_host
uv run ctest --preset spike -R 'DrainRing|PciemBridge'
```

🐧 The drive needs pciem loaded, which needs root, and pciem needs memory the kernel leaves alone, which needs a reboot. On x86, set aside 64 MiB at 256 MiB, inside the RAM below 1 GiB (`/sys/firmware/memmap` says where yours is), in a file of its own so that it is easy to take out. The three backslashes become one in `grub.cfg`, which GRUB turns into the `$` the kernel wants:

```sh
echo 'GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT memmap=64M\\\$0x10000000"' | sudo tee /etc/default/grub.d/pciem.cfg
sudo update-grub
sudo reboot
# and after it
sudo insmod build/pciem/kernel/pciem.ko pciem_phys_region=0x10000000:0x4000000
```

`sudo rm /etc/default/grub.d/pciem.cfg && sudo update-grub` and a reboot take it out again. Secure Boot refuses an unsigned module; it was off on the machine the spike ran on.

Then a drive goes on the bus with no root, as `/dev/pciem` is open to everyone, and `lsblk` lists it:

```sh
build/dev/spikes/pciem/spike_pciem_host behavioral --least-timeout 1
build/dev/spikes/pciem/spike_pciem_host stand-in
PYTHONPATH=python uv run python spikes/pciem/describe_ssd.py > build/pciem-ssd.board
build/dev/spikes/pciem/spike_pciem_host zephyr --board build/pciem-ssd.board
```

`--log` prints each controller register write and each admin command with its answer, and `--dry-run` builds and boots a drive without going on the bus. 💡 `--least-timeout 1` is for the behavioral drive, which says its controller is ready in no time, which Linux takes for "do not wait" (the report has why).

To use the drives as disks, with root, all three in turn, logs in `build/pciem-run/`:

```sh
sudo spikes/pciem/exercise.sh
```

⚠️ It finds the drive by where it is, under pciem's bus, and never by name. On a machine with NVMe drives of its own, the puppet's is not `nvme0n1`.
