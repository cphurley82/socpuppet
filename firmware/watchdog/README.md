# The watchdog firmware 🧦

A Zephyr application that gets itself reset twice and says why each time it starts. It is what `tests/python/test_rom_boot.py` boots to show a [system controller](../../docs/models/system-controller.md) and a [watchdog](../../docs/models/watchdog.md) at work.

What it prints, over its three starts (Zephyr's banner, and the boot ROM's line when it is booted from a flash, come before each `reset cause`):

```text
reset cause: power-on
watchdog: ran out, and interrupted
reset cause: software
watchdog: fed 1
watchdog: fed 2
watchdog: fed 3
watchdog: fed 4
watchdog: fed 5
watchdog: fed 6
watchdog: no more feeding
reset cause: watchdog
```

1. **From power-on**, it has the watchdog interrupt when it runs out, and not reset. It waits for that interrupt, and then asks for a reset with `sys_reboot()`.
2. **Reset by its own asking**, it has the watchdog reset when it runs out. It feeds it for twice as long as that would take, and then stops and waits.
3. **Reset by the watchdog**, it says so, and is done.

Nothing in it is socpuppet's but one header, for the name of the register it reads. The watchdog is driven through Zephyr's watchdog API by Zephyr's own driver (`sifive,wdt`), the system controller is read through Zephyr's `syscon` driver, and `sys_reboot()` is Zephyr's. socpuppet's SoC supplies the one function Zephyr leaves to a SoC, `sys_arch_reboot()`, which writes the system controller's `RESET_REQUEST`.

It is built by `firmware/build.py` for `socpuppet_host` and `socpuppet_ssd`, which is one board for each kind of CPU and of interrupt controller.

💡 What tells the three starts apart is the system controller's `RESET_CAUSE`, and nothing the firmware kept: a reset loses what was in memory. Booted from a ROM, the image is copied out of the flash again each time.
