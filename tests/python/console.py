"""What a console printed, as plain text.

A shell dresses what it prints in escape sequences, which move and colour
a terminal; a test wants the words. UEFI's shell and Linux's both do.
"""

import re

#: An escape sequence as both shells send them: ESC, `[`, numbers and
#: semicolons, and a letter.
ESCAPE_SEQUENCE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def plain(console):
    """`console` without the escape sequences a terminal moves and colours
    with."""
    return ESCAPE_SEQUENCE.sub("", console)
