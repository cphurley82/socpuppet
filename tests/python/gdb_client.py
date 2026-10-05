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

    def program_counter(self):
        """The address of the instruction the CPU will execute next."""
        # Register 32 (0x20) is the program counter on RISC-V, after the 32
        # general registers. Its value comes as hex, lowest byte first.
        return int.from_bytes(bytes.fromhex(self.ask("p20")), "little")

    def read_memory(self, address, length):
        """`length` bytes of memory starting at `address`."""
        return bytes.fromhex(self.ask(f"m{address:x},{length:x}"))

    def continue_(self):
        """Let the CPU run. The server says nothing until it stops again."""
        self.send("c")

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
