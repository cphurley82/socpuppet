"""Just enough of a GDB client to talk to a CPU model's debug server.

GDB and the thing it debugs speak the "remote serial protocol": text
packets of the form `$<body>#<checksum>`, each acknowledged with a `+`.
Using it directly keeps the tests free of a GDB binary.
"""

import socket


class GdbClient:
    """One connection to a GDB server on this machine."""

    def __init__(self, port, timeout=10):
        self._socket = socket.create_connection(("127.0.0.1", port), timeout)

    def close(self):
        self._socket.close()

    def send(self, body):
        """Send one packet, without waiting for what comes back."""
        checksum = sum(body.encode()) % 256
        self._socket.sendall(f"${body}#{checksum:02x}".encode())

    def ask(self, body):
        """Send one packet and return the body of the reply."""
        self.send(body)
        return self._reply()

    def wait_for_the_cpu_to_stop(self):
        """Return once the CPU is stopped where it starts, having run nothing.

        A CPU with a GDB port stops before its first instruction, and it
        gets there when the simulation runs. A debugger can attach sooner,
        and a register read then would be answered at once, with what the
        register held before the CPU's reset (docs/upstream.md). A read of
        memory is answered by the simulation's own thread, which sees to
        it when the CPU has stopped. What the read gets does not matter.
        """
        self.ask("m0,1")

    def program_counter(self):
        """The address of the instruction the CPU will execute next."""
        # Register 32 (0x20) is the program counter on RISC-V, after the 32
        # general registers. Its value comes as hex, lowest byte first.
        return int.from_bytes(bytes.fromhex(self.ask("p20")), "little")

    def read_memory(self, address, length):
        """`length` bytes of memory starting at `address`.

        A server may answer with fewer bytes than it was asked for, and
        DBT-RISE's sends at most 184 at a time. So this asks again for
        the rest, as GDB does.
        """
        read = b""
        while len(read) < length:
            reply = self.ask(f"m{address + len(read):x},{length - len(read):x}")
            if not reply or reply.startswith("E"):
                raise RuntimeError(
                    f"The server would not read memory at "
                    f"{address + len(read):#x}: {reply!r}."
                )
            read += bytes.fromhex(reply)
        return read

    def target_description(self):
        """The XML a server describes its CPU with: which kind of core,
        and which registers it has."""
        xml = ""
        while True:
            # The answer comes a piece at a time. Each piece starts with
            # `m` if there is more to come and `l` if it is the last.
            piece = self.ask(f"qXfer:features:read:target.xml:{len(xml):x},400")
            if piece[:1] not in ("m", "l"):
                raise RuntimeError(
                    f"The server gave no target description: {piece!r}."
                )
            xml += piece[1:]
            if piece[0] == "l":
                return xml

    def monitor(self, command):
        """What the server prints for GDB's `monitor <command>`.

        These are commands of the server's own, outside the protocol.
        """
        return bytes.fromhex(
            self.ask("qRcmd," + command.encode().hex())
        ).decode()

    def set_breakpoint(self, address, size=4):
        """Have the CPU stop when it is about to execute what is at `address`.

        `size` is how many bytes the instruction there takes: four, or two
        for a compressed one.
        """
        # Z0 is a breakpoint that the debugger would write into memory on
        # hardware.
        reply = self.ask(f"Z0,{address:x},{size:x}")
        if reply != "OK":
            raise RuntimeError(f"The server refused the breakpoint: {reply!r}.")

    def continue_(self):
        """Let the CPU run. The server says nothing until it stops again."""
        self.send("c")

    def wait_for_a_stop(self):
        """Wait for a CPU that was told to continue to stop, at a breakpoint.

        Returns what the server said of it: `S05` is "stopped by a trap".
        """
        return self._reply()

    def _reply(self):
        received = b""
        while b"#" not in received or len(received.split(b"#")[-1]) < 2:
            chunk = self._socket.recv(4096)
            if not chunk:
                raise ConnectionError("The GDB server closed the connection.")
            received += chunk
        self._socket.sendall(b"+")
        return received[
            received.index(b"$") + 1 : received.rindex(b"#")
        ].decode()
