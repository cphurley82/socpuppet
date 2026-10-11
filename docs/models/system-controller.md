# System controller

`sp.SystemController(die=..., boot_address=...)` · C++ `socpuppet::SystemController` · registry name `system_controller`

## What it stands for

The small block every SoC has that answers a CPU's questions about itself and owns its reset. 🎓 Vendors call it a system controller, a reset and clock controller, or a PMU, and it is usually the first thing a boot ROM reads: which chip is this, where do I boot from, and why am I starting?

## What it does

- **Answers three questions.** `DIE` and `BOOT_ADDRESS` read what the board gave the block, and `RESET_CAUSE` reads why the CPU last came out of reset.
- **Owns the CPU's reset.** 🎓 A wire has one driver, and a CPU's reset has more than one reason to rise. So each reason is an input here, and `reset` is the one line to the CPU:
  - `hold` keeps the CPU in reset for as long as it is high. A [die-to-die link](d2d-link.md) holds the other die's CPU this way until the link is trained.
  - `bite` is a watchdog's line. When it rises, `reset` is pulsed and the cause reads `WATCHDOG`. A line that stays high is one bite.
  - Firmware asks by writing a one to `RESET_REQUEST`. `reset` is pulsed and the cause reads `SOFTWARE`.
- **A pulse is 1 µs long**, which is ten ticks of the 10 MHz clock a socpuppet CPU has.
- **Either input may be left unconnected**, and is then tied low.
- **A debugger looks and does not touch.** `peek` reads a register. `poke` is refused with a `PermissionError` that says why: the one register that can be written asks for a reset.

```python
syscon = compute.add("syscon", sp.SystemController(die=0, boot_address=0x1020_0000))
bus.map(syscon.socket, base=0x0010_0000)
platform.connect(link.a.reset, syscon.hold)
platform.connect(syscon.reset, cpu.reset)
```

## The registers

<!-- regs:system_controller start -->

| Offset | Name | Access | What it is |
| --- | --- | --- | --- |
| `0x00` | `DIE` | read | Which die the CPU is on, as the number the board gave it. |
| `0x04` | `BOOT_ADDRESS` | read | Where the CPU's boot ROM finds the image to start: the address of the image's header. |
| `0x08` | `RESET_CAUSE` | read | Why the CPU was last reset. 0 `POWER_ON`: The power came on, and nothing has reset the CPU since. 1 `WATCHDOG`: The watchdog bit: firmware stopped feeding it. 2 `SOFTWARE`: Firmware asked, by writing to `RESET_REQUEST`. |
| `0x0C` | `RESET_REQUEST` | write | Asks for a reset of the CPU. Reads as zero. Bit 0 `RESET`: Write a one to reset the CPU. |

<!-- regs:system_controller end -->

A write to one of the three that firmware only reads is a bus error, as is an access that is not of one whole register.

## What firmware sees

A devicetree node with two names, ours first:

```dts
syscon: syscon@100000 {
	compatible = "socpuppet,system-controller", "syscon";
	reg = <0x0 0x100000 0x0 0x20>;
};
```

🎓 `syscon` is what Zephyr and Linux both call a block of registers that other code reaches into. Zephyr has a driver for any node of that name, so firmware needs none of ours: `syscon_read_reg()` with an offset from `socpuppet/regs/system_controller.h`. [`firmware/watchdog`](../../firmware/watchdog/README.md) reads why it was reset that way.

💡 Zephyr's `sys_reboot()` ends here too. RISC-V has no common way to reset a system, so Zephyr leaves the last step, `sys_arch_reboot()`, to the SoC, and socpuppet's SoC writes `RESET_REQUEST` (`soc/socpuppet/reboot.c` in the Zephyr module, built when `CONFIG_REBOOT` is on and the devicetree has a system controller).

## What it leaves out

- **Clocks, power and pins.** A real system controller gates clocks, sequences power rails and muxes pins. This one has the reset and nothing else.
- **A reset that reaches anything but the CPU.** `reset` is one wire, and a board says what it goes to.
- **A cause for a hold.** A CPU held at power-on and let go reads `POWER_ON`. So does one that is held a second time, later, by the same line: nothing here tells the two apart.
- **A cause that is cleared.** `RESET_CAUSE` is the last reason and stays so until the next. Real ones often keep a bit for each cause until firmware clears it.

## Under the hood

`SystemControllerLogic` (`src/socpuppet/core/system_controller_logic.h`) is the registers and the three reasons, with no simulator in it, and `tests/cpp/unit/system_controller_logic_test.cpp` holds it. `SystemController` is the SystemC wrapper: one process writes `reset`, and an event ends a pulse.

⚠️ A pulse of 1 µs is far shorter than the 100 µs a busy CPU model may run ahead of the clock, and the borrowed CPU used to miss such a pulse and stop the simulation. It is patched ([upstream.md](../upstream.md)), and `tests/cpp/platform/system_controller_test.cpp` has a watchdog bite a CPU that is busy and one that is asleep.
