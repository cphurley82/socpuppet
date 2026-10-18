"""QEMU's log of what its CPU ran, as a list of addresses.

🎓 Asked through its debugger (`monitor log exec,nochain`, with
`monitor one-insn-per-tb on`), QEMU writes a line for each instruction
QBox's CPU is about to run, with its address among the CPU's state;
`socpuppet.qemu_trace.pcs` reads the addresses out, so that two runs can
be compared line by line and the first that differs found.
"""

from socpuppet import qemu_trace

#: What QEMU wrote for the program of test_gdb.py: the first block was
#: stopped before it ran and started again, and then each instruction ran.
LOG = """\
Trace 0: 0x7ea788000100 [001411ad/0000000000000100/02c24003/ff022201]
Stopped execution of TB chain before 0x7ea788000100 [0000000000000100]
Trace 0: 0x7ea788000240 [001411ad/0000000000000100/02c24003/ff022201]
Trace 0: 0x7ea788000380 [001411ad/0000000000000104/02c24003/ff022201]
Trace 0: 0x7ea7880004c0 [001411ad/0000000000000108/02c24003/ff022201]
Trace 0: 0x7ea788000640 [001411ad/000000000000010c/02c24003/ff022201]
"""


class TestWhenQemusLogIsRead:
    def test_it_gives_the_address_of_each_instruction_that_ran_in_order(self):
        assert qemu_trace.pcs(LOG) == [0x100, 0x104, 0x108, 0x10C]

    def test_lines_that_are_not_traces_are_left_out(self):
        log = "spam\nTrace 0: 0x1 [0/00000000000000a0/0/0] \neggs\n"

        assert qemu_trace.pcs(log) == [0xA0]
