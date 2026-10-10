"""UCIe, as far as Python needs it: a link's registers and its sideband.

🎓 UCIe (Universal Chiplet Interconnect Express) is the open standard for
joining two dies in one package. socpuppet's `sp.D2dLink()` is modelled on
it, from public sources only, and is not a compliant implementation.

Two things here. The register block one end of the link shows the firmware
on its die, which is UCIe's Link DVSEC and the blocks it points at, and
the sideband packets the two ends send each other, so that a trace of a
link can be read as a capture of its management traffic:

    for record in platform.trace:
        if not record.source.endswith("sideband_peer_initiator"):
            continue  # ⚠️ the mainband is traced too, and its bytes are
            # not packets, however much they may look like one
        packet = ucie.SidebandPacket.from_bytes(record.data)
        if packet is not None:
            print(record.time, packet.description())

⚠️ The offsets and the packet layout are the same ones
`socpuppet::UcieLinkRegisters` and `socpuppet::SidebandPacket` have in
C++. Nothing checks that the two agree: what keeps them in step is that
the manager stand-in (`sp.IoManager`) drives the real model through them.
"""

from __future__ import annotations

import dataclasses
import struct
from enum import IntEnum

# ---- The link's register block, as its die's bus reaches it. The block
# ---- has more in it than this (the capability's headers, a register
# ---- locator, the training state); these are the ones something here
# ---- drives, so these are the ones kept honest.
#: Starting the link, and what it is doing.
LINK_CONTROL = 0x10
LINK_STATUS = 0x14
LINK_EVENT_NOTIFICATION = 0x18
#: In the block the register locator points at: the reset this end drives
#: on its die, and a way to break the link on purpose.
DIE_RESET = 0x24
FAULT_INJECTION = 0x28
#: The sideband mailbox, which reaches the other end's registers.
MAILBOX_OPCODE = 0x40
MAILBOX_ADDRESS = 0x48
MAILBOX_DATA = 0x50
MAILBOX_TRIGGER = 0x58
MAILBOX_STATUS = 0x5C

#: Link control. Both bits clear themselves: they are an action, not a
#: setting.
START_TRAINING = 1 << 0
RETRAIN_LINK = 1 << 1
#: Link status.
LINK_UP = 1 << 0
LINK_STATUS_CHANGED = 1 << 2
#: Link event notification.
STATUS_CHANGED_INTERRUPT = 1 << 0
#: The mailbox's status: whether there is an access still waiting to be
#: answered.
MAILBOX_BUSY = 1 << 8


class Opcode(IntEnum):
    """What a sideband packet is for."""

    MEMORY_READ_32B = 0b00000
    MEMORY_WRITE_32B = 0b00001
    COMPLETION_WITHOUT_DATA = 0b10000
    COMPLETION_WITH_32B_DATA = 0b10001
    MESSAGE_WITHOUT_DATA = 0b10010
    MESSAGE_WITH_64B_DATA = 0b11011


class Status(IntEnum):
    """How a register access on the other die turned out."""

    SUCCESS = 0
    UNSUPPORTED_REQUEST = 2


#: How a status reads in a line of a trace.
_STATUS_NAMES: dict[int, str] = {
    Status.SUCCESS: "success",
    Status.UNSUPPORTED_REQUEST: "unsupported request",
}

#: How many bytes of data each opcode carries, besides the header.
_DATA_BYTES = {
    Opcode.MEMORY_READ_32B: 0,
    Opcode.MEMORY_WRITE_32B: 4,
    Opcode.COMPLETION_WITHOUT_DATA: 0,
    Opcode.COMPLETION_WITH_32B_DATA: 4,
    Opcode.MESSAGE_WITHOUT_DATA: 0,
    Opcode.MESSAGE_WITH_64B_DATA: 8,
}

#: The last word of the handshake: the two ends agreeing that the link is
#: theirs to use, which is the end of training.
MESSAGE_RDI_RSP_ACTIVE = (0x02, 0x01)

#: The messages the two ends send each other on the way up, and after, by
#: (code, subcode). UCIe writes a message's name in braces, and so do
#: these.
_MESSAGES = {
    (0x91, 0x00): "{SBINIT Out of Reset}",
    (0x95, 0x01): "{SBINIT Done Request}",
    (0x9A, 0x01): "{SBINIT Done Response}",
    (0xA5, 0x00): "{MBINIT.PARAM configuration request}",
    (0xAA, 0x00): "{MBINIT.PARAM configuration response}",
    (0xA5, 0x02): "{MBINIT.CAL Done Request}",
    (0xAA, 0x02): "{MBINIT.CAL Done Response}",
    (0x01, 0x01): "{LinkMgmt.RDI.Req.Active}",
    MESSAGE_RDI_RSP_ACTIVE: "{LinkMgmt.RDI.Rsp.Active}",
    (0x01, 0x0A): "{LinkMgmt.RDI.Req.LinkError}",
    (0x01, 0x0B): "{LinkMgmt.RDI.Req.Retrain}",
    (0x09, 0x02): "{ErrMsg Fatal}",
}

#: What the two kinds of register access are called.
_ACCESS_NAMES = {
    Opcode.MEMORY_READ_32B: "MemoryRead_32b",
    Opcode.MEMORY_WRITE_32B: "MemoryWrite_32b",
}

#: One field of the 64-bit header: where UCIe starts it, and how wide.
_FIELDS = {
    "opcode": (0, 5),
    "msgcode": (14, 8),
    "srcid": (29, 3),
    "msgsubcode": (32, 8),
    "msginfo": (40, 16),
    "dstid": (56, 3),
    "control_parity": (62, 1),
    "data_parity": (63, 1),
}
_HEADER_BYTES = 8


def _field(header: int, name: str) -> int:
    shift, width = _FIELDS[name]
    return (header >> shift) & ((1 << width) - 1)


@dataclasses.dataclass(frozen=True, kw_only=True)
class SidebandPacket:
    """One packet on the sideband: a 64-bit header and what it carries.

    A register access reads its address out of the same bits a message's
    subcode and information are in, which is how UCIe fits both into one
    header.
    """

    opcode: Opcode
    # Who the packet is from and to. Zero is no id UCIe assigns: nothing
    # here builds a packet to send, so the defaults are only for a test
    # that names the fields it cares about.
    srcid: int = 0
    dstid: int = 0
    msgcode: int = 0
    msgsubcode: int = 0
    msginfo: int = 0
    control_parity: bool = False
    data_parity: bool = False
    data: int = 0

    @classmethod
    def from_bytes(cls, raw: bytes) -> SidebandPacket | None:
        """The packet those bytes are, or None if they are no packet.

        A trace of a link's sideband has one of these in each record's
        data. Bytes too few for a header, an opcode UCIe does not assign,
        or a length that opcode does not have, are no packet.
        """
        if len(raw) < _HEADER_BYTES:
            return None
        header = struct.unpack_from("<Q", raw)[0]
        try:
            opcode = Opcode(_field(header, "opcode"))
        except ValueError:
            return None
        if len(raw) != _HEADER_BYTES + _DATA_BYTES[opcode]:
            return None
        carried = raw[_HEADER_BYTES:]
        return cls(
            opcode=opcode,
            srcid=_field(header, "srcid"),
            dstid=_field(header, "dstid"),
            msgcode=_field(header, "msgcode"),
            msgsubcode=_field(header, "msgsubcode"),
            msginfo=_field(header, "msginfo"),
            control_parity=bool(_field(header, "control_parity")),
            data_parity=bool(_field(header, "data_parity")),
            data=int.from_bytes(carried, "little"),
        )

    @property
    def address(self) -> int:
        """The register a register access is for, on the other end."""
        return self.msgsubcode | (self.msginfo << 8)

    def description(self) -> str:
        """The packet in one line, as a reader of a trace wants it."""
        carries_data = _DATA_BYTES[self.opcode] != 0
        if self.opcode in _ACCESS_NAMES:
            access = f"{_ACCESS_NAMES[self.opcode]} {self.address:#x}"
            return f"{access} = {self.data:#x}" if carries_data else access
        if self.opcode in (
            Opcode.COMPLETION_WITHOUT_DATA,
            Opcode.COMPLETION_WITH_32B_DATA,
        ):
            how = _STATUS_NAMES.get(self.msgcode, f"status {self.msgcode:#x}")
            answer = f" {self.data:#x}" if carries_data else ""
            return f"Completion{answer}, {how}"
        return _MESSAGES.get(
            (self.msgcode, self.msgsubcode),
            f"message {self.msgcode:#04x}/{self.msgsubcode:#04x}",
        )
