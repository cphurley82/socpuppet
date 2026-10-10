"""NVMe frontend: the registers.

The CPU's side of the frontend: what the host has done, the command that is
waiting, how it went, and the queues the firmware has agreed to.

Generated from regs/nvme_frontend.rdl by tools/regs.py. Do not edit: change
the register map and run `uv run python tools/lint.py --fix`.
"""

#: How many bytes of address space the block takes.
SIZE = 0x80

#: What the firmware says of itself.
CONTROL = 0x00
#: The firmware is ready for the host's commands. The host sees it as
#: `CSTS.RDY`.
CONTROL_READY = 1 << 0

#: What the host has done, and whether a command is waiting.
STATUS = 0x04
#: The host has enabled the controller.
STATUS_ENABLED = 1 << 0
#: The host has disabled the controller, which is a reset. Writing the one
#: says the firmware holds nothing from before it.
STATUS_DISABLED = 1 << 1
#: A command is waiting. Set for exactly as long as one is.
STATUS_COMMAND_WAITING = 1 << 2

#: Which bits of `STATUS` raise `cpu_irq` while they are set.
INTERRUPT_ENABLE = 0x08
INTERRUPT_ENABLE_ENABLED = 1 << 0
INTERRUPT_ENABLE_DISABLED = 1 << 1
INTERRUPT_ENABLE_COMMAND_WAITING = 1 << 2

#: What the frontend has, for the firmware to tell the host.
LIMITS = 0x0C
#: How many pairs of I/O queues, which is eight.
LIMITS_IO_QUEUE_PAIRS_MASK = 0x0000FFFF
LIMITS_IO_QUEUE_PAIRS_SHIFT = 0
#: How many interrupt vectors it has for the host.
LIMITS_VECTORS_MASK = 0xFFFF0000
LIMITS_VECTORS_SHIFT = 16

#: Which submission queue the waiting command came from. 0 is the admin queue.
COMMAND_QUEUE = 0x10

#: The first 32 bits of the completion: the command's answer, for the few that
#: have one.
COMPLETION_RESULT = 0x14

#: How the command went, laid out as the status field of a completion is, less
#: the phase bit. The other bits read back as zero.
COMPLETION_STATUS = 0x18
#: The status code, zero for success.
COMPLETION_STATUS_CODE_MASK = 0x000000FF
COMPLETION_STATUS_CODE_SHIFT = 0
#: Which list of codes that is from.
COMPLETION_STATUS_TYPE_MASK = 0x00000700
COMPLETION_STATUS_TYPE_SHIFT = 8

#: Has the completion of the waiting command posted. Reads as zero.
COMPLETION_POST = 0x1C
#: Write a one, and nothing else, to post it.
COMPLETION_POST_NOW = 1 << 0

#: A queue to create: which,
QUEUE_ID = 0x20

#: where it is in the host's memory, the low 32 bits,
QUEUE_BASE_LOW = 0x24

#: and the high 32 bits,
QUEUE_BASE_HIGH = 0x28

#: its last slot, which is its size less one,
QUEUE_LAST = 0x2C

#: and what goes with it: a completion queue's interrupt vector, or the
#: completion queue a submission queue's completions go to.
QUEUE_LINK = 0x30

#: Write which kind of queue to create it. Reads as zero.
QUEUE_CREATE = 0x34
#: Create the completion queue the queue registers describe.
QUEUE_CREATE_COMPLETION_QUEUE = 1
#: Create the submission queue they describe.
QUEUE_CREATE_SUBMISSION_QUEUE = 2

#: The waiting command, 64 bytes, read whole or a piece at a time. Zeros when
#: none is waiting.
COMMAND = 0x40
COMMAND_SIZE = 0x40
