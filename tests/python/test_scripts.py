import os
import signal
import subprocess
import sys
import textwrap

import pytest

import socpuppet as sp
from scripts import writing


def master_with_ram(script):
    """A scripted bus master wired straight to a 0x100-byte RAM."""
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
    ram = platform.add("ram", sp.Memory(size=0x100))
    platform.connect(cpu.socket, ram.socket)
    platform.build()
    return platform


@pytest.mark.platform
class TestWhenAScriptYieldsAWriteOfBytes:
    def test_the_bytes_are_in_memory_from_that_address_on(self):
        def script():
            yield sp.write(0x10, bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66]))

        platform = master_with_ram(script)

        platform.run()

        assert platform.peek(0x10, 6) == bytes(
            [0x11, 0x22, 0x33, 0x44, 0x55, 0x66]
        )


class TestWhenAWriteOfBytesIsGivenANumber:
    def test_it_is_refused_and_the_error_points_at_write32(self):
        with pytest.raises(TypeError, match="write32"):
            sp.write(0x10, 0xC0FFEE)


class TestWhenAReadOfBytesIsGivenANegativeLength:
    def test_it_is_refused_and_the_error_names_the_length(self):
        with pytest.raises(ValueError, match="-1"):
            sp.read(0x10, -1)


@pytest.mark.platform
class TestWhenAScriptYieldsAReadOfBytes:
    def test_the_bytes_sent_back_are_what_memory_holds(self):
        read_back = []

        def script():
            read_back.append((yield sp.read(0x10, 6)))

        platform = master_with_ram(script)
        platform.poke(0x10, bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66]))

        platform.run()

        assert read_back == [bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66])]


@pytest.mark.platform
class TestWhenAScriptYieldsARead:
    def test_the_value_sent_back_is_what_the_bus_returned(self):
        def script():
            yield sp.write32(0x10, 0xC0FFEE)
            value = yield sp.read32(0x10)
            yield sp.write32(0x20, value)

        platform = master_with_ram(script)

        platform.run()

        assert platform.peek32(0x20) == 0xC0FFEE


@pytest.mark.platform
class TestWhenAScriptYieldsAWait:
    def test_simulated_time_has_advanced_by_that_much_when_it_carries_on(self):
        def script():
            yield sp.wait(sp.ns(10))
            yield sp.write32(0x10, 1)

        platform = master_with_ram(script)

        platform.run_until(lambda: platform.peek32(0x10) == 1)

        assert platform.time == sp.ns(10)


@pytest.mark.platform
class TestWhenAScriptExpectsAValueThatIsNotInMemory:
    def test_run_raises_and_the_error_names_address_expected_and_actual(self):
        def script():
            yield sp.write32(0x10, 0xBAD)
            yield sp.expect32(0x10, 0xC0FFEE)

        platform = master_with_ram(script)

        with pytest.raises(sp.ExpectationFailed) as error:
            platform.run()

        assert "0x10" in str(error.value)
        assert "0xc0ffee" in str(error.value)
        assert "0xbad" in str(error.value)

    def test_memory_can_still_be_peeked_afterwards(self):
        def script():
            yield sp.write32(0x10, 0xBAD)
            yield sp.expect32(0x10, 0xC0FFEE)

        platform = master_with_ram(script)
        with pytest.raises(sp.ExpectationFailed):
            platform.run()

        assert platform.peek32(0x10) == 0xBAD


@pytest.mark.platform
class TestWhenAScriptRaises:
    def test_run_raises_the_same_exception(self):
        class ScriptBroke(Exception):
            pass

        def script():
            yield sp.write32(0x10, 1)
            raise ScriptBroke("the strings got tangled")

        platform = master_with_ram(script)

        with pytest.raises(ScriptBroke, match="the strings got tangled"):
            platform.run()

    def test_the_traceback_points_into_the_script(self):
        def tangled_script():
            yield sp.write32(0x10, 1)
            raise RuntimeError("the strings got tangled")

        platform = master_with_ram(tangled_script)

        with pytest.raises(RuntimeError) as error:
            platform.run()

        assert "tangled_script" in [frame.name for frame in error.traceback]


@pytest.mark.platform
class TestWhenAScriptRecursesTooDeeply:
    def test_run_raises_recursion_error(self):
        def recurse_forever():
            return recurse_forever()

        def script():
            yield sp.write32(0x10, 1)
            recurse_forever()

        platform = master_with_ram(script)

        with pytest.raises(RecursionError):
            platform.run()


@pytest.mark.platform
class TestWhenAScriptYieldsSomethingThatIsNotAnOperation:
    def test_run_raises_and_the_error_says_what_a_script_may_yield(self):
        def script():
            yield 42

        platform = master_with_ram(script)

        with pytest.raises(TypeError) as error:
            platform.run()

        assert "42" in str(error.value)
        assert "sp.write32" in str(error.value)


@pytest.mark.platform
class TestWhenTwoScriptedMastersRunAtOnce:
    def test_each_script_runs_in_full(self):
        platform = sp.Platform()
        cpus = []
        for name in ("first", "second"):
            group = platform.group(name)
            cpu = group.add(
                "cpu", sp.ScriptedBusMaster(writing([(0x10, 1), (0x14, 2)]))
            )
            ram = group.add("ram", sp.Memory(size=0x100))
            platform.connect(cpu.socket, ram.socket)
            cpus.append(cpu)
        platform.build()

        platform.run()

        assert [
            (
                platform.peek32(0x10, via=cpu.socket),
                platform.peek32(0x14, via=cpu.socket),
            )
            for cpu in cpus
        ] == [(1, 2), (1, 2)]


class TestWhenAScriptIsNotAGeneratorFunction:
    def test_a_generator_object_is_refused_and_the_error_says_to_pass_the_function(
        self,
    ):
        def script():
            yield sp.write32(0x10, 1)

        with pytest.raises(TypeError) as error:
            sp.ScriptedBusMaster(script())

        assert "Pass the function" in str(error.value)

    def test_a_function_that_never_yields_is_refused_and_the_error_says_to_yield(
        self,
    ):
        def not_a_script():
            return 42

        with pytest.raises(TypeError) as error:
            sp.ScriptedBusMaster(not_a_script)

        assert "yield" in str(error.value)


class TestWhenAnOperationIsGivenAValueThatDoesNotFitIn32Bits:
    def test_it_is_refused_and_the_error_names_the_value(self):
        with pytest.raises(ValueError, match="0x100000001"):
            sp.write32(0x10, 0x1_0000_0001)

    def test_a_negative_value_is_refused_too(self):
        with pytest.raises(ValueError, match="-1"):
            sp.write32(0x10, -1)


class TestWhenARunIsInterruptedFromTheKeyboard:
    def test_the_process_stops_with_keyboard_interrupt(self):
        endless = start_python(
            """
            import socpuppet as sp

            def script():
                print("running", flush=True)
                while True:
                    yield sp.wait(sp.ns(1))

            platform = sp.Platform()
            cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
            ram = platform.add("ram", sp.Memory(size=0x100))
            platform.connect(cpu.socket, ram.socket)
            platform.build()
            platform.run()
            """
        )
        endless.stdout.readline()  # wait until the script is running

        errors = interrupt_and_collect_errors(endless)

        assert "KeyboardInterrupt" in errors


# Far longer than an interrupt takes. It is only here so that a broken build
# fails instead of hanging.
HANG_GUARD_SECONDS = 30


def interrupt_and_collect_errors(process):
    process.send_signal(signal.SIGINT)
    try:
        _, errors = process.communicate(timeout=HANG_GUARD_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        raise
    return errors


def start_python(code):
    """Start a snippet in a fresh interpreter, with its output piped back."""
    return subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(code)],
        env={"PYTHONPATH": os.pathsep.join(sys.path)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def two_writes_ten_and_fifteen_nanoseconds_in():
    yield sp.wait(sp.ns(10))
    yield sp.write32(0x10, 1)
    yield sp.wait(sp.ns(5))
    yield sp.write32(0x10, 2)


@pytest.mark.platform
class TestWhenThePlatformIsStepped:
    def test_time_moves_to_the_next_scheduled_activity_and_that_activity_happens(
        self,
    ):
        platform = master_with_ram(two_writes_ten_and_fifteen_nanoseconds_in)

        platform.step()

        assert platform.time == sp.ns(10)
        assert platform.peek32(0x10) == 1

    def test_step_returns_true_while_the_script_still_has_something_scheduled(
        self,
    ):
        platform = master_with_ram(two_writes_ten_and_fifteen_nanoseconds_in)

        assert platform.step()

    def test_step_returns_false_once_the_script_has_finished(self):
        platform = master_with_ram(writing([(0x10, 1)]))
        platform.run()

        assert not platform.step()


@pytest.mark.platform
class TestWhenThePlatformRunsUntilACondition:
    def test_it_stops_as_soon_as_the_condition_holds(self):
        platform = master_with_ram(two_writes_ten_and_fifteen_nanoseconds_in)

        held = platform.run_until(lambda: platform.peek32(0x10) == 1)

        assert held
        assert platform.time == sp.ns(10)

    def test_it_says_so_when_the_simulation_ends_without_the_condition_holding(
        self,
    ):
        platform = master_with_ram(two_writes_ten_and_fifteen_nanoseconds_in)

        assert not platform.run_until(lambda: platform.peek32(0x10) == 3)

    def test_it_gives_up_once_the_timeout_has_passed(self):
        def endless():
            while True:
                # Not a divisor of the timeout, so time can only land on the
                # timeout by stopping there, never by a step ending on it.
                yield sp.wait(sp.ns(7))

        platform = master_with_ram(endless)

        held = platform.run_until(lambda: False, timeout=sp.ns(100))

        assert not held
        assert platform.time == sp.ns(100)
