# Real-time clock

`sp.Rtc(time=...)` · C++ `socpuppet::Rtc` · registry name `rtc`

## What it stands for

The clock that knows the time of day. 🎓 A CPU counts time from when it started, and forgets it when it stops; a real-time clock keeps the date and time, on a battery of its own on a real board, so that an operating system can set its own clock from it as it starts.

This is the Goldfish real-time clock: not a chip, but the clock of Android's emulator, which QEMU's `virt` machine has too, and which Linux's `rtc-goldfish` drives. 🚧 The rest of this page comes with the clock's model.

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
