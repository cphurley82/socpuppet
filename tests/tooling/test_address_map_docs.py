"""tools/address_map_docs.py, which keeps the docs' address tables true."""

import subprocess
import sys
from pathlib import Path

from socpuppet.address_map import format_address, format_size
from socpuppet.boards import host as host_board
from socpuppet.boards import io_manager as io_manager_board
from socpuppet.boards import ssd as ssd_board

TOOL = Path(__file__).resolve().parents[2] / "tools" / "address_map_docs.py"


def test_when_a_table_is_not_what_the_board_describes_check_fails_and_says_how_to_repair_it(
    tmp_path,
):
    page = a_page(tmp_path, "address-map:ssd", "| a table | from long ago |\n")

    result = address_map_docs("check", page)

    assert result.returncode != 0
    assert str(page) in result.stdout
    assert "lint.py --fix" in result.stdout


def test_when_the_tables_are_written_check_then_passes(tmp_path):
    page = a_page(tmp_path, "address-map:ssd")

    address_map_docs("write", page)

    assert address_map_docs("check", page).returncode == 0


def test_when_the_tables_are_written_what_is_outside_the_markers_stays_as_it_was(
    tmp_path,
):
    page = a_page(tmp_path, "address-map:ssd")

    address_map_docs("write", page)

    assert page.read_text().startswith("# A page\n\nWords before.\n\n")
    assert page.read_text().endswith("\n\nWords after.\n")


def test_an_address_table_has_a_row_for_what_answers_with_a_link_to_its_models_page(
    tmp_path,
):
    page = a_page(tmp_path, "address-map:ssd")

    address_map_docs("write", page)

    row = cells(page, starting=ssd_board.FRONTEND_BASE)
    assert row["What answers"] == "`ssd.frontend.cpu`"
    assert row["Its model"].endswith("](models/nvme-frontend.md)")


def test_a_row_says_how_many_bytes_answer_there(tmp_path):
    page = a_page(tmp_path, "address-map:ssd")

    address_map_docs("write", page)

    assert cells(page, starting=ssd_board.BUFFER_BASE)["Size"] == format_size(
        ssd_board.BUFFER_SIZE
    )


def test_an_end_of_a_link_has_the_links_page_for_its_model(tmp_path):
    page = a_page(tmp_path, "address-map:io-manager")

    address_map_docs("write", page)

    row = cells(page, starting=io_manager_board.LINK_BASE)
    assert row["Its model"].endswith("](models/d2d-link.md)")


def test_a_row_behind_a_translating_window_says_which_and_where_it_starts(
    tmp_path,
):
    page = a_page(tmp_path, "address-map:host")

    address_map_docs("write", page)

    uart = host_board.IO_BASE + host_board.UART_OFFSET
    assert cells(page, starting=uart)["Through"] == (
        f"`compute.bus` from `{format_address(host_board.IO_BASE)}`"
    )


def test_a_row_behind_a_window_that_does_not_translate_says_the_addresses_are_the_same(
    tmp_path,
):
    page = a_page(tmp_path, "address-map:io-manager-compute")

    address_map_docs("write", page)

    through = cells(page, starting=io_manager_board.SCRATCH_BASE)["Through"]
    assert through == "`compute.bus`, same addresses"


def test_a_row_on_the_masters_own_bus_is_through_nothing(tmp_path):
    page = a_page(tmp_path, "address-map:host")

    address_map_docs("write", page)

    assert cells(page, starting=host_board.RAM_BASE)["Through"] == ""


def test_the_table_of_what_a_drive_adds_has_the_msi_bridge_and_not_the_ram(
    tmp_path,
):
    page = a_page(tmp_path, "address-map:host-drive")

    address_map_docs("write", page)

    written = page.read_text()
    assert f"`{format_address(host_board.MSI_BASE)}`" in written
    assert f"`{format_address(host_board.RAM_BASE)}`" not in written


def test_an_interrupt_table_row_says_which_controller_which_number_and_which_line(
    tmp_path,
):
    page = a_page(tmp_path, "interrupts:ssd")

    address_map_docs("write", page)

    assert (
        f"| `ssd.plic` | {ssd_board.DMA_SOURCE} | `ssd.dma.irq` |"
        in page.read_text()
    )


def test_the_interrupt_table_of_the_host_with_the_ssd_has_lines_of_both_interrupt_controllers(
    tmp_path,
):
    page = a_page(tmp_path, "interrupts:host-ssd")

    address_map_docs("write", page)

    written = page.read_text()
    assert (
        f"| `compute.plic` | {host_board.MSI_SOURCE} | `compute.msi.irq0` |"
        in written
    )
    assert (
        f"| `ssd.plic` | {ssd_board.FRONTEND_SOURCE} | `ssd.frontend.cpu_irq` |"
        in written
    )


def test_when_a_marker_names_a_table_there_is_none_of_check_fails_and_lists_the_ones_there_are(
    tmp_path,
):
    page = a_page(tmp_path, "address-map:spam")

    result = address_map_docs("check", page)

    assert result.returncode != 0
    assert "address-map:spam" in result.stdout
    assert "address-map:ssd" in result.stdout


def test_when_a_table_starts_and_never_ends_check_fails_and_says_which_marker_is_missing(
    tmp_path,
):
    page = tmp_path / "page.md"
    page.write_text("# A page\n\n<!-- address-map:ssd start -->\n\nWords.\n")

    result = address_map_docs("check", page)

    assert result.returncode != 0
    assert "<!-- address-map:ssd end -->" in result.stdout


def a_page(directory, table, between=""):
    """A page with markers for one table, and `between` between them."""
    page = directory / "page.md"
    page.write_text(
        "# A page\n\nWords before.\n\n"
        f"<!-- {table} start -->\n{between}<!-- {table} end -->\n"
        "\nWords after.\n"
    )
    return page


def address_map_docs(command, page):
    """Run tools/address_map_docs.py on a page."""
    return subprocess.run(
        [
            sys.executable,
            str(TOOL),
            command,
            str(page),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def cells(page, *, starting):
    """The one row of `page`'s table for the address `starting`, by column."""
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in page.read_text().splitlines()
        if line.startswith("|")
    ]
    header = rows[0]
    (row,) = (row for row in rows if row[0] == f"`{format_address(starting)}`")
    return dict(zip(header, row, strict=True))
