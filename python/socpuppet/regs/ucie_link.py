"""UCIe link: the registers.

One end of the die-to-die link: UCIe's Link DVSEC, the reset and fault
registers it locates, and the sideband mailbox.

Generated from regs/ucie_link.rdl by tools/regs.py. Do not edit: change the
register map and run `uv run python tools/lint.py --fix`.
"""

#: How many bytes of address space the block takes.
SIZE = 0x100

#: PCIe's extended capability header.
EXTENDED_CAPABILITY_HEADER = 0x00
EXTENDED_CAPABILITY_HEADER_AT_RESET = 0x00010023
#: 0x0023, which says a designated vendor-specific capability.
EXTENDED_CAPABILITY_HEADER_CAPABILITY_ID_MASK = 0x0000FFFF
EXTENDED_CAPABILITY_HEADER_CAPABILITY_ID_SHIFT = 0
#: The capability's version.
EXTENDED_CAPABILITY_HEADER_VERSION_MASK = 0x000F0000
EXTENDED_CAPABILITY_HEADER_VERSION_SHIFT = 16
#: Where the next capability is. There is none.
EXTENDED_CAPABILITY_HEADER_NEXT_MASK = 0xFFF00000
EXTENDED_CAPABILITY_HEADER_NEXT_SHIFT = 20

#: DVSEC header 1: whose capability it is.
DVSEC_HEADER_1 = 0x04
DVSEC_HEADER_1_AT_RESET = 0x1000D2DE
#: 0xD2DE, which is the vendor number UCIe registered.
DVSEC_HEADER_1_VENDOR_ID_MASK = 0x0000FFFF
DVSEC_HEADER_1_VENDOR_ID_SHIFT = 0
#: The capability's revision.
DVSEC_HEADER_1_REVISION_MASK = 0x000F0000
DVSEC_HEADER_1_REVISION_SHIFT = 16
#: How long the capability is, in bytes: the whole block.
DVSEC_HEADER_1_LENGTH_MASK = 0xFFF00000
DVSEC_HEADER_1_LENGTH_SHIFT = 20

#: DVSEC header 2: which of the vendor's capabilities it is.
DVSEC_HEADER_2 = 0x08
DVSEC_HEADER_2_AT_RESET = 0x00000001
#: ⚠️ Ours: public sources do not give UCIe's number for the link DVSEC.
DVSEC_HEADER_2_DVSEC_ID_MASK = 0x0000FFFF
DVSEC_HEADER_2_DVSEC_ID_SHIFT = 0

#: UCIe's link control. Both bits are an action, clear themselves, and read as
#: zero.
CONTROL = 0x10
#: Start link training.
CONTROL_START_TRAINING = 1 << 0
#: Retrain the link, from reset.
CONTROL_RETRAIN = 1 << 1

#: UCIe's link status.
STATUS = 0x14
#: The link is up.
STATUS_UP = 1 << 0
#: The link is being trained.
STATUS_TRAINING = 1 << 1
#: The link has gone up or come down since this was cleared.
STATUS_CHANGED = 1 << 2
#: The other die has reported an error nothing can be done about.
STATUS_UNCORRECTABLE_FATAL = 1 << 3

#: UCIe's link event notification: what raises `irq`.
EVENT_NOTIFICATION = 0x18
#: Interrupt while the status says the link has changed.
EVENT_NOTIFICATION_STATUS_CHANGED = 1 << 0

#: The register locator: where the block of the link's own registers is. ⚠️
#: Its layout is ours.
REGISTER_LOCATOR = 0x1C
REGISTER_LOCATOR_AT_RESET = 0x00002001
#: Which block it is.
REGISTER_LOCATOR_BLOCK_MASK = 0x000000FF
REGISTER_LOCATOR_BLOCK_SHIFT = 0
#: Where the block starts, from the start of the capability.
REGISTER_LOCATOR_OFFSET_MASK = 0xFFFFFF00
REGISTER_LOCATOR_OFFSET_SHIFT = 8

#: Which training state the link is in. ⚠️ The numbers are ours.
TRAINING_STATE = 0x20
#: Held in reset, as every link is for 4 ms after power-on.
TRAINING_STATE_RESET = 0
#: The sideband is being brought up.
TRAINING_STATE_SBINIT = 1
#: The mainband's parameters are being agreed.
TRAINING_STATE_MBINIT = 2
#: The mainband is being trained.
TRAINING_STATE_MBTRAIN = 3
#: The two ends are agreeing that the link is theirs to use.
TRAINING_STATE_LINKINIT = 4
#: The link is up, and carries the dies' traffic.
TRAINING_STATE_ACTIVE = 5
#: Training failed, or the link was broken. Only a retrain leaves this state.
TRAINING_STATE_TRAIN_ERROR = 6

#: The reset this end drives on its own die.
DIE_RESET = 0x24
DIE_RESET_AT_RESET = 0x00000001
#: The die is held in reset. The other die lets it go by writing a zero here,
#: through its mailbox.
DIE_RESET_ASSERTED = 1 << 0

#: A way to break the link on purpose. Reads as zero.
FAULT_INJECTION = 0x28
#: Write a one to break the link.
FAULT_INJECTION_BREAK = 1 << 0

#: What the next access to the other end is to be.
MAILBOX_OPCODE = 0x40
#: UCIe's opcode for it, which is five bits of a sideband packet.
MAILBOX_OPCODE_CODE_MASK = 0x0000001F
MAILBOX_OPCODE_CODE_SHIFT = 0
#: Read a register of the other end.
MAILBOX_OPCODE_CODE_MEMORY_READ_32B = 0
#: Write one.
MAILBOX_OPCODE_CODE_MEMORY_WRITE_32B = 1

#: Which register of the other end: its offset in the block there.
MAILBOX_ADDRESS = 0x48

#: What to write. Reads as what the last read brought back.
MAILBOX_DATA = 0x50

#: Sends the access. Reads as zero.
MAILBOX_TRIGGER = 0x58
#: Write a one to send it.
MAILBOX_TRIGGER_GO = 1 << 0

#: How the last access went, and whether one is still on its way.
MAILBOX_STATUS = 0x5C
#: How it went.
MAILBOX_STATUS_CODE_MASK = 0x00000007
MAILBOX_STATUS_CODE_SHIFT = 0
#: The other end did it.
MAILBOX_STATUS_CODE_SUCCESS = 0
#: There is no such register at the other end, or it cannot be written.
MAILBOX_STATUS_CODE_UNSUPPORTED_REQUEST = 2
#: An access has been sent and not yet answered.
MAILBOX_STATUS_BUSY = 1 << 8
