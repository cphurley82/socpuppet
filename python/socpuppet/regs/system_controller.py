"""System controller: the registers.

What a CPU asks about itself and its last reset, and the registers that reset
it and switch it off.

Generated from regs/system_controller.rdl by tools/regs.py. Do not edit:
change the register map and run `uv run python tools/lint.py --fix`.
"""

#: How many bytes of address space the block takes.
SIZE = 0x20

#: Which die the CPU is on, as the number the board gave it.
DIE = 0x00

#: Where the CPU's boot ROM finds the image to start: the address of the
#: image's header.
BOOT_ADDRESS = 0x04

#: Why the CPU was last reset.
RESET_CAUSE = 0x08
#: The power came on, and nothing has reset the CPU since.
RESET_CAUSE_POWER_ON = 0
#: The watchdog bit: firmware stopped feeding it.
RESET_CAUSE_WATCHDOG = 1
#: Firmware asked, by writing to `RESET_REQUEST`.
RESET_CAUSE_SOFTWARE = 2

#: Asks for a reset of the CPU. Reads as zero.
RESET_REQUEST = 0x0C
#: Write a one to reset the CPU.
RESET_REQUEST_RESET = 1 << 0

#: Switches the CPU off: holds it in reset for good. Reads as one once it has
#: been.
POWER_OFF = 0x10
#: Write a one to switch the CPU off. A zero changes nothing.
POWER_OFF_OFF = 1 << 0
