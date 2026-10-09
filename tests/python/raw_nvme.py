"""A bare NVMe host for tests: it sends any command and says how it went.

`sp.NvmeHost` is a driver, and a driver only sends what a drive should be
sent. Tests of what a drive refuses need to send the rest. This host is
written from the NVMe specification, and shares nothing with the driver.

Its queues have eight entries each. The admin queues are in the first two
pages of the memory it is given, and the one pair of I/O queues it can
ask for is in the next two.
"""

import struct
from typing import NamedTuple

import socpuppet as sp

# The controller registers, and the doorbells after them.
_CAP = 0x00
_CC = 0x14
_CSTS = 0x1C
_AQA = 0x24
_ASQ = 0x28
_ACQ = 0x30
_DOORBELLS = 0x1000

_ENTRIES = 8
_PAGE = 4096

# Admin opcodes.
CREATE_IO_SUBMISSION_QUEUE = 0x01
CREATE_IO_COMPLETION_QUEUE = 0x05
IDENTIFY = 0x06
SET_FEATURES = 0x09
# I/O opcodes.
FLUSH = 0x00
WRITE = 0x01
READ = 0x02


class Completion(NamedTuple):
    """How a command went, as its completion says."""

    #: The status: which list its code is from, and the code. List 0 is
    #: the one every command shares, list 1 is the command's own, and code
    #: 0 of list 0 is success.
    status: tuple[int, int]
    #: The command's answer, for the few that have one.
    result: int


SUCCESS = (0, 0)


class _Queues:
    def __init__(self, queue_id: int, submissions: int, completions: int):
        self.queue_id = queue_id
        self.submissions = submissions
        self.completions = completions
        self.tail = 0
        self.head = 0
        self.phase = 1
        self.next_command_id = 0


class RawNvmeHost:
    """A host that submits commands as given, one at a time.

    `registers` is where the controller's registers are, and `memory` is
    host memory for the queues: four pages. The controller's first
    interrupt line has to reach this master's `irq`.
    """

    def __init__(self, *, registers: int, memory: int):
        self._registers = registers
        self._memory = memory
        self._admin = _Queues(0, memory, memory + _PAGE)
        self._io = _Queues(1, memory + 2 * _PAGE, memory + 3 * _PAGE)

    def enable(self):
        """Says where the admin queues are, sets CC.EN and waits for ready."""
        self._admin = _Queues(0, self._memory, self._memory + _PAGE)
        self._io = _Queues(
            1, self._memory + 2 * _PAGE, self._memory + 3 * _PAGE
        )
        last = _ENTRIES - 1
        yield sp.write32(self._registers + _AQA, last << 16 | last)
        yield from sp.write64(self._registers + _ASQ, self._admin.submissions)
        yield from sp.write64(self._registers + _ACQ, self._admin.completions)
        yield sp.write32(self._registers + _CC, 1)
        yield from self._wait_until_ready_is(1)

    def disable(self):
        """Clears CC.EN, which is a controller reset, and waits for it."""
        yield sp.write32(self._registers + _CC, 0)
        yield from self._wait_until_ready_is(0)

    def create_io_queues(self):
        """Asks for I/O queue pair 1, on the first interrupt vector."""
        size = (_ENTRIES - 1) << 16
        created = yield from self.admin(
            opcode=CREATE_IO_COMPLETION_QUEUE,
            data=self._io.completions,
            dword10=size | 1,
            dword11=0,
        )
        assert created.status == SUCCESS, created
        created = yield from self.admin(
            opcode=CREATE_IO_SUBMISSION_QUEUE,
            data=self._io.submissions,
            dword10=size | 1,
            dword11=1 << 16,
        )
        assert created.status == SUCCESS, created

    def admin(self, **command):
        """Submits a command to the admin queue. Returns its Completion."""
        return (yield from self._submit(self._admin, **command))

    def io(self, **command):
        """Submits a command to I/O queue 1. Returns its Completion."""
        return (yield from self._submit(self._io, **command))

    def _submit(
        self,
        queues,
        *,
        opcode,
        namespace=0,
        data=0,
        more_data=0,
        dword10=0,
        dword11=0,
        dword12=0,
    ):
        command_id = queues.next_command_id
        queues.next_command_id += 1
        yield sp.write(
            queues.submissions + 64 * queues.tail,
            struct.pack(
                "<BBHI16xQQIII12x",
                opcode,
                0,
                command_id,
                namespace,
                data,
                more_data,
                dword10,
                dword11,
                dword12,
            ),
        )
        queues.tail = (queues.tail + 1) % _ENTRIES
        yield sp.write32(self._doorbell(queues, 0), queues.tail)

        yield sp.wait_irq()
        entry = yield sp.read(queues.completions + 16 * queues.head, 16)
        # The result, four bytes that are reserved, how far the submission
        # queue has been read and which queue it is, the identifier, and
        # the phase bit with the status above it.
        result, _, _, _, completed_id, status = struct.unpack("<IIHHHH", entry)
        assert status & 1 == queues.phase, "no new completion"
        assert completed_id == command_id
        queues.head = (queues.head + 1) % _ENTRIES
        if queues.head == 0:
            queues.phase ^= 1
        yield sp.write32(self._doorbell(queues, 1), queues.head)
        return Completion(
            status=((status >> 9) & 0x7, (status >> 1) & 0xFF), result=result
        )

    def _doorbell(self, queues, which):
        return self._registers + _DOORBELLS + 4 * (2 * queues.queue_id + which)

    def _wait_until_ready_is(self, wanted):
        # CAP.TO, in the top byte of the low half, is how long to wait at
        # most, in units of 500 ms. A controller that says 0 is ready, or
        # not ready, at once.
        low = yield sp.read32(self._registers + _CAP)
        for _ in range(1 + 500 * (low >> 24)):
            if (yield sp.read32(self._registers + _CSTS)) & 1 == wanted:
                return
            yield sp.wait(sp.ms(1))
        raise AssertionError(f"CSTS.RDY never became {wanted}")
