# Watchdog

`sp.Watchdog()` · C++ `socpuppet::Watchdog` · registry name `watchdog`

## What it stands for

The timer that resets a CPU whose firmware has hung. 🎓 A watchdog is a counter that firmware has to keep setting back to zero, which is called feeding it. Firmware that is stuck stops feeding, the count reaches a value firmware chose, and the watchdog resets the CPU: it bites. Nearly every embedded system has one, because the alternative to a reset nobody asked for is a device that needs someone to walk over and switch it off and on.

This one is the watchdog of SiFive's FE310, which Zephyr has a driver for (`sifive,wdt`), so firmware uses it through Zephyr's ordinary watchdog API and nothing of socpuppet's.

## What it does

```python
wdt = compute.add("wdt", sp.Watchdog())
bus.map(wdt.socket, base=0x0010_1000)
platform.connect(wdt.bite, syscon.bite)        # what resets the CPU
platform.connect(wdt.irq, aplic.source17)      # its interrupt
```

| | |
|---|---|
| **Registers on the bus** (`socket`) | A page, 32 bits each. |
| **The bite** (`bite`) | Rises when the watchdog runs out with its reset enabled, for one tick of its clock. Connect it to a [system controller](system-controller.md)'s `bite`. |
| **The interrupt** (`irq`) | High while the watchdog has run out and firmware has not cleared the bit that says so. |

- **It counts ticks of a 32,768 Hz clock**, the frequency of a watch crystal, while firmware has it enabled.
- **It compares the count shifted right by a scale** of 0 to 15 with a 16-bit compare value. So a period is from one tick, 30.5 µs, to eighteen hours.
- **When the two meet it bites or it interrupts**, as firmware chose. A bite puts the watchdog back as it is out of reset: off, and at zero. So firmware that starts again has all the time it needs to set it up again.
- **Every write takes a key first**, and uses it up. A stray write from firmware that has gone wrong changes nothing.
- **Feeding is a write of one value**, `0xD09F00D`, to one register, with the key.

### The registers

| Offset | Register | |
|---|---|---|
| `0x00` | `wdogcfg` | The scale in bits 3 to 0. Bit 8, `rsten`: bite when it runs out. Bit 9, `zerocmp`: start the count over when it runs out. Bit 12, `enalways`: count. Bit 13, `encoreawake`: count while the CPU is awake, which here is the same. Bit 28, `ip0`: it has run out, which is the interrupt. |
| `0x08` | `wdogcount` | The count. |
| `0x10` | `wdogs` | The count shifted right by the scale: what is compared. |
| `0x18` | `wdogfeed` | Written with `0xD09F00D`, to set the count to zero. |
| `0x1C` | `wdogkey` | Written with `0x51F15E`, to unlock the next write. Reads as 1 while unlocked. |
| `0x20` | `wdogcmp` | The compare value. `0xFFFF` out of reset, which with a scale of zero is two seconds. |

⚠️ **Zephyr cannot switch this watchdog off.** Its driver's `wdt_disable` asks for the longest period there is, and leaves it counting. Eighteen hours is as good as off for a test, and it is not off.

## What it leaves out

- **The rest of the always-on block.** The model is of the whole block, with a real-time clock, a power manager and backup registers, which are there as registers that hold what is written and do nothing. The page has them, from `0x40` up.
- **Counting only while the CPU is awake.** The `encoreawake` bit counts as `enalways` does: the model is not told when its CPU sleeps.
- **A window.** A watchdog that also bites when it is fed too soon is another kind. Zephyr's API has a field for it, and its driver for this watchdog refuses a timeout that sets one.
- **A count that knows how far ahead its CPU is.** A CPU model runs up to a quantum ahead of the simulation's clock, 100 µs by default, and the [machine timer](machine-timer.md) counts that lead in. The watchdog goes by the simulation's clock alone, so a feed or a read of the count can be three ticks out. A watchdog's periods are thousands of ticks.
- **The count's 31 bits.** The real count wraps at 31 bits, eighteen hours in. This one does not wrap.

## In a devicetree

```dts
compute_wdt: watchdog@101000 {
	compatible = "sifive,wdt";
	reg = <0x0 0x101000 0x0 0x1000>;
	interrupt-parent = <&compute_aplic>;
	interrupts = <17 1 4>;
};
```

⚠️ The interrupt is given the short way, as `interrupt-parent` and `interrupts`, because Zephyr's binding for this watchdog requires a property of that name, and its driver will not build for a node without one.

The devicetree also names it, at the top of the tree:

```dts
aliases {
	watchdog0 = &compute_wdt;
};
```

🎓 An alias is a name that firmware and boards agree on beforehand. Zephyr's watchdog test and samples ask for `watchdog0` and get whichever watchdog the board says that is, so the same program runs on boards that label theirs differently. Of two watchdogs on one CPU's bus, the one at the lower address has the name.

## Under the hood

💡 This one is borrowed. The model is the always-on block from [VPV-Peripherals](https://github.com/VP-Vibes/VPV-Peripherals), by Minres, which had the watchdog's registers and nothing behind them. The watchdog is added by `cmake/patches/vpv-peripherals-aon-watchdog.patch`, which is written up in [upstream.md](../upstream.md) as a feature to offer.

The count is not stepped once a tick. The model keeps what the count was at some moment, works out what it is when someone reads it, and schedules one event for the moment it will run out. A watchdog that is fed on time costs the simulation nothing but the feeds.

socpuppet wraps it in an adapter (`src/socpuppet/models/watchdog.cpp`) that brings out the watchdog's two lines and the register page, and ties the block's reset button off. The patch has the block write each line from one process, so the lines are bound straight through, where the [PLIC](plic.md)'s adapter has to copy its line to keep to one writer.

It is held to `WatchdogContract` (`tests/cpp/contracts/watchdog_contract.h`).
