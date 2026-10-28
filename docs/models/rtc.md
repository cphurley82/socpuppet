# Real-time clock

`sp.Rtc(time=...)` · C++ `socpuppet::Rtc` · registry name `rtc`

## What it stands for

The clock that knows the time of day. 🎓 A CPU counts time from when it started, and forgets it when it stops; a real-time clock keeps the date and time, on a battery of its own on a real board, so that an operating system can set its own clock from it as it starts. It can also be set for a time to come, an alarm, and interrupt then.

This is the Goldfish real-time clock: not a chip, but the clock of Android's emulator, which QEMU's `virt` machine has too, and which Linux's `rtc-goldfish` drives. It is small, as real clocks go: a count of nanoseconds since 1970, and an alarm.

## What it does

```python
import datetime

rtc = io.add("rtc", sp.Rtc(time=datetime.datetime(2026, 10, 26, tzinfo=datetime.UTC)))
bus.map(rtc.cpu, base=0x100F_2000)
platform.connect(rtc.irq, aplic.source31)
```

| | |
|---|---|
| **Registers on the bus** (`cpu`) | A page, 32 bits each. |
| **The interrupt** (`irq`) | Up when the alarm has gone off, while firmware has the interrupt enabled and has not cleared it. |

- **`time`** is what the clock reads as the simulation starts: a `datetime` with a time zone, or nanoseconds since 1970. With none it reads 1970 itself, as a clock whose battery was never in does. A `datetime` with no time zone is refused, since which moment it means cannot be told. The host takes it as `host(rtc_time=...)`.
- **It keeps the simulation's time**, not the wall's: a second of simulated time is a second on the clock, however long it took to simulate.
- **The time is 64 bits in two halves.** Reading the low half keeps the high half as it was then, for the next read of `TIME_HIGH`, so a carry between the two reads cannot tear the time. Writing the high half and then the low sets it.
- **The alarm** is set by writing its time, high half first: it goes off at that time, or at once if the time has passed, and is then no longer set. Setting the clock past the alarm sets it off too.

### The registers

<!-- regs:rtc start -->

| Offset | Name | Access | What it is |
| --- | --- | --- | --- |
| `0x000` | `TIME_LOW` | read, write | The low half of the time. Reading it keeps the high half as it was then, for `TIME_HIGH`; writing it sets the time, with the high half written to `TIME_HIGH` before. |
| `0x004` | `TIME_HIGH` | read, write | The high half of the time: as it was when `TIME_LOW` was last read, or as last written, for a write of `TIME_LOW` to set. |
| `0x008` | `ALARM_LOW` | read, write | The low half of the alarm's time. Writing it sets the alarm, with the high half written to `ALARM_HIGH` before. |
| `0x00C` | `ALARM_HIGH` | read, write | The high half of the alarm's time. |
| `0x010` | `IRQ_ENABLED` | read, write | Whether the alarm, when it goes off, raises the interrupt. Bit 0 `ENABLED`. |
| `0x014` | `CLEAR_ALARM` | write | Writing anything takes the alarm off. |
| `0x018` | `ALARM_STATUS` | read | Whether the alarm is set and has not gone off. Bit 0 `SET`. |
| `0x01C` | `CLEAR_INTERRUPT` | write | Writing anything clears the interrupt the alarm raised. |

<!-- regs:rtc end -->

## What it leaves out

- **A battery.** The clock reads what it was given each time the simulation starts, and nothing it was set to survives the run.
- **The time a CPU running ahead sees.** A register is read at the time the access is made, which a CPU running a quantum ahead of the simulation's clock gives; the alarm goes off by the simulation's clock, up to a quantum later than such a CPU expected.
- **The alarm under Zephyr.** socpuppet's Zephyr driver sets and gets the time, and does not offer the alarm.

## In a devicetree

Both trees have it as `google,goldfish-rtc`, with its registers and its interrupt; Zephyr's gives it the alias `rtc`, which Zephyr's own test of a clock looks for. On the host:

```dts
io_rtc: rtc@100f2000 {
	compatible = "google,goldfish-rtc";
	reg = <0x0 0x100f2000 0x0 0x1000>;
	interrupts-extended = <&io_aplic 31 1 4>;
};
```

🐧 Linux's `rtc-goldfish` drives it, and the stock kernel sets its own clock from it as it starts (`RTC_HCTOSYS`).

## Under the hood

💡 The registers are written once, in `regs/rtc.rdl`, and the logic is plain C++, `src/socpuppet/core/rtc_logic.cpp`, with no simulation kernel: it is told the simulated time with each call, and says when its alarm is next due. The SystemC wrapper, `src/socpuppet/models/rtc.h`, waits until then, or until firmware writes a register.

📮 Zephyr has no driver for the clock, so socpuppet's module has one, `drivers/rtc/rtc_goldfish.c`; [upstream.md](../upstream.md) has it as one to send. Zephyr's own `tests/drivers/rtc/rtc_api` passes on it (`tests/python/test_m18_exit.py`, and twister).

`tests/cpp/unit/rtc_logic_test.cpp` holds the logic, and `tests/cpp/platform/rtc_test.cpp` the clock keeping the simulation's time and its alarm raising its line.
