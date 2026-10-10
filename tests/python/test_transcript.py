"""Several consoles, heard as one story (socpuppet.Transcript)."""

import pytest

import socpuppet as sp
from socpuppet.transcript import Line, render

SPAM_UART = 0x1000
EGGS_UART = 0x2000


@pytest.mark.platform
class TestWhenTwoConsolesAreListenedToAsARunGoesOn:
    def test_the_lines_are_in_the_order_they_were_said_each_with_who_said_it(
        self,
    ):
        # The transcript is given `spam` before `eggs`, and `eggs` speaks
        # first.
        def script():
            yield from say(EGGS_UART, "And eggs.\n")
            yield from pause()
            yield from say(SPAM_UART, "Lovely spam!\n")
            yield from pause()
            yield from say(EGGS_UART, "Eggs again.\n")

        _, transcript = two_consoles(script)

        run_listening(transcript)

        assert [(line.who, line.text) for line in transcript.lines] == [
            ("eggs", "And eggs."),
            ("spam", "Lovely spam!"),
            ("eggs", "Eggs again."),
        ]

    def test_each_line_has_the_time_of_the_listen_that_found_it(self):
        def script():
            yield from say(SPAM_UART, "Lovely spam!\n")
            yield sp.wait(sp.us(10))
            yield from say(EGGS_UART, "And eggs.\n")

        platform, transcript = two_consoles(script)

        platform.run(sp.us(5))
        transcript.listen()
        platform.run(sp.us(10))
        transcript.listen()

        assert [line.time for line in transcript.lines] == [
            sp.us(5),
            sp.us(15),
        ]


@pytest.mark.platform
class TestWhenAConsoleIsListenedToInTheMiddleOfALine:
    def test_the_line_is_noted_once_it_is_whole_and_not_before(self):
        def script():
            yield from say(SPAM_UART, "Lovely ")
            yield sp.wait(sp.us(10))
            yield from say(SPAM_UART, "spam!\n")

        platform, transcript = two_consoles(script)

        platform.run(sp.us(5))
        transcript.listen()
        in_the_middle = list(transcript.lines)
        platform.run(sp.us(10))
        transcript.listen()

        assert in_the_middle == []
        assert [line.text for line in transcript.lines] == ["Lovely spam!"]


@pytest.mark.platform
class TestWhenAConsoleEndsItsLinesWithACarriageReturnAndALineFeed:
    def test_a_lines_text_is_without_them(self):
        # Which is how Zephyr's console ends a line.
        def script():
            yield from say(SPAM_UART, "Lovely spam!\r\n")

        _, transcript = two_consoles(script)

        run_listening(transcript)

        assert [line.text for line in transcript.lines] == ["Lovely spam!"]


@pytest.mark.platform
class TestWhenATranscriptRunsThePlatformUntilACondition:
    def test_it_stops_when_the_condition_holds_having_heard_all_that_was_said(
        self,
    ):
        def script():
            yield from say(EGGS_UART, "And eggs.\n")
            yield from pause()
            yield from say(SPAM_UART, "Lovely spam!\n")
            yield from pause()
            yield from say(EGGS_UART, "Eggs again.\n")

        _, transcript = two_consoles(script)

        held = transcript.run_until(
            lambda: "Lovely spam!" in [line.text for line in transcript.lines]
        )

        assert held
        assert [(line.who, line.text) for line in transcript.lines] == [
            ("eggs", "And eggs."),
            ("spam", "Lovely spam!"),
        ]


class TestWhenATranscriptsLinesAreRendered:
    def test_each_is_a_row_of_when_in_milliseconds_who_and_what_was_said(self):
        lines = [
            Line(sp.us(1500), "spam", "Lovely spam!"),
            Line(sp.ms(20), "eggs", "And eggs."),
        ]

        header, *rows = render(lines, color=False).splitlines()

        assert header.split() == ["ms", "who", "said"]
        assert [row.split(maxsplit=2) for row in rows] == [
            ["1.5", "spam", "Lovely spam!"],
            ["20.0", "eggs", "And eggs."],
        ]

    def test_it_is_plain_text_where_color_is_not_wanted(self):
        lines = [Line(sp.us(1500), "spam", "Lovely spam!")]

        assert "\x1b[" not in render(lines, color=False)

    def test_it_is_colored_where_color_is_wanted(self):
        lines = [Line(sp.us(1500), "spam", "Lovely spam!")]

        assert "\x1b[" in render(lines, color=True)


def say(uart, text):
    """The steps of a script that prints `text` through the UART at `uart`."""
    for byte in text.encode():
        # A byte written to a 16550's first register is sent.
        yield sp.write(uart, bytes([byte]))


def pause():
    """The steps of a script that let simulated time pass.

    A write takes no simulated time, so a pause is what puts one line
    before another.
    """
    yield sp.wait(sp.us(10))


def two_consoles(script):
    """A platform where `script` prints through two UARTs, and their transcript.

    The consoles are called `spam` and `eggs`.
    """
    platform = sp.Platform()
    speaker = platform.add("speaker", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    spam = platform.add("spam", sp.Ns16550())
    eggs = platform.add("eggs", sp.Ns16550())
    platform.connect(speaker.socket, bus.target)
    bus.map(spam.socket, base=SPAM_UART)
    bus.map(eggs.socket, base=EGGS_UART)
    platform.build()
    return platform, sp.Transcript(platform, {"spam": spam, "eggs": eggs})


def run_listening(transcript):
    """Run to the end of the script, listening as it goes."""
    transcript.run_until(lambda: False)
