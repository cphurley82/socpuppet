"""Real-time clock: the registers.

The time of day, in nanoseconds since 1970, and an alarm at a time to come.

Generated from regs/rtc.rdl by tools/regs.py. Do not edit: change the register
map and run `uv run python tools/lint.py --fix`.
"""

#: How many bytes of address space the block takes.
SIZE = 0x1000

#: The low half of the time. Reading it keeps the high half as it was then,
#: for `TIME_HIGH`; writing it sets the time, with the high half written to
#: `TIME_HIGH` before.
TIME_LOW = 0x000

#: The high half of the time: as it was when `TIME_LOW` was last read, or as
#: last written, for a write of `TIME_LOW` to set.
TIME_HIGH = 0x004

#: The low half of the alarm's time. Writing it sets the alarm, with the high
#: half written to `ALARM_HIGH` before.
ALARM_LOW = 0x008

#: The high half of the alarm's time.
ALARM_HIGH = 0x00C

#: Whether the alarm, when it goes off, raises the interrupt.
IRQ_ENABLED = 0x010
IRQ_ENABLED_ENABLED = 1 << 0

#: Writing anything takes the alarm off.
CLEAR_ALARM = 0x014

#: Whether the alarm is set and has not gone off.
ALARM_STATUS = 0x018
ALARM_STATUS_SET = 1 << 0

#: Writing anything clears the interrupt the alarm raised.
CLEAR_INTERRUPT = 0x01C
