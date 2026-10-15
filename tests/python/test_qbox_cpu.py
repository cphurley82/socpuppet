"""The QBox CPU, as described: what it is, and the host board with it."""

import pytest

import socpuppet as sp
from socpuppet.boards.boot import ROM_BASE, from_rom
from socpuppet.boards.host import RAM_BASE, host


class TestAQboxCpuOfAWidthOtherThan64Bits:
    def test_is_refused_and_the_error_says_which_cpu_has_it(self):
        with pytest.raises(ValueError, match=r"64-bit.*DbtRiseCpu"):
            sp.QboxCpu(xlen=32, reset_vector=0)


class TestAQboxCpuWithOtherExtensionsOrModes:
    @pytest.mark.parametrize(
        "described", [{"isa": "imac"}, {"modes": "m"}], ids=["isa", "modes"]
    )
    def test_is_refused_and_the_error_says_what_it_has(self, described):
        with pytest.raises(ValueError, match=r'isa="gc", modes="msu"'):
            sp.QboxCpu(xlen=64, reset_vector=0, **described)


class TestAQboxCpusNodeInTheDevicetree:
    @pytest.mark.parametrize(
        "connected", [set(), {"csr"}], ids=["alone", "with an IMSIC"]
    )
    def test_is_the_node_of_the_other_cpu_with_the_same_core(self, connected):
        the_other = sp.DbtRiseCpu(
            xlen=64, reset_vector=0, isa="gc", modes="msu"
        )

        assert sp.QboxCpu(xlen=64, reset_vector=0).cpu_node(
            "cpu0", connected
        ) == the_other.cpu_node("cpu0", connected)


class TestTheHostWithQboxsCpu:
    def test_has_a_qbox_cpu_that_starts_in_its_ram(self):
        cpu = host(cpu="qbox_cpu").cpu.component

        assert isinstance(cpu, sp.QboxCpu)
        assert cpu.reset_vector == RAM_BASE

    def test_booted_from_its_rom_has_a_qbox_cpu_that_starts_there(self):
        cpu = host(cpu="qbox_cpu", boot=from_rom).cpu.component

        assert isinstance(cpu, sp.QboxCpu)
        assert cpu.reset_vector == ROM_BASE

    def test_has_the_same_devicetree_as_with_the_other_cpu(self):
        assert host(cpu="qbox_cpu").platform.devicetree() == (
            host().platform.devicetree()
        )


class TestTheHostAskedForACpuItHasNot:
    def test_is_refused_and_the_error_names_what_was_asked_for_and_the_cpus_it_has(
        self,
    ):
        with pytest.raises(
            ValueError, match=r'"spam".*"dbt_rise_cpu".*"qbox_cpu"'
        ):
            host(cpu="spam")  # type: ignore[arg-type]


class TestTheHostWithQboxsCpuAndADebugger:
    def test_is_refused_and_the_error_says_which_cpu_has_one(self):
        with pytest.raises(ValueError, match=r"gdb_port.*dbt_rise"):
            host(cpu="qbox_cpu", gdb_port=1234)


class TestTheHostWithSocpuppetCpuSet:
    def test_to_qbox_cpu_has_qboxs_cpu_when_none_is_named(self, monkeypatch):
        monkeypatch.setenv("SOCPUPPET_CPU", "qbox_cpu")

        assert isinstance(host().cpu.component, sp.QboxCpu)

    def test_to_qbox_cpu_has_the_one_named(self, monkeypatch):
        monkeypatch.setenv("SOCPUPPET_CPU", "qbox_cpu")

        assert isinstance(host(cpu="dbt_rise_cpu").cpu.component, sp.DbtRiseCpu)

    def test_to_dbt_rise_cpu_has_dbt_rises_cpu(self, monkeypatch):
        monkeypatch.setenv("SOCPUPPET_CPU", "dbt_rise_cpu")

        assert isinstance(host().cpu.component, sp.DbtRiseCpu)

    def test_to_a_cpu_there_is_not_is_refused_and_the_error_names_the_ones_there_are(
        self, monkeypatch
    ):
        monkeypatch.setenv("SOCPUPPET_CPU", "spam")

        with pytest.raises(
            ValueError, match=r'"spam".*"dbt_rise_cpu".*"qbox_cpu"'
        ):
            host()
