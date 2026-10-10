"""tools/lint.py on the docs' address-map page."""

# A page whose one table has not been written yet. The table is one with
# no links in it, which would lead nowhere from a throwaway repository.
STALE = (
    "# The address map\n\n"
    "<!-- interrupts:ssd start -->\n<!-- interrupts:ssd end -->\n"
)


def test_when_the_address_map_page_has_a_stale_table_lint_fails_and_names_the_page(
    repo, lint
):
    (repo / "docs").mkdir()
    (repo / "docs/address-map.md").write_text(STALE)

    result = lint()

    assert result.returncode != 0
    assert "❌ address-map" in result.stdout
    assert "docs/address-map.md" in result.stdout


def test_when_run_with_fix_a_stale_table_is_written_again_and_then_passes_lint(
    repo, lint
):
    (repo / "docs").mkdir()
    (repo / "docs/address-map.md").write_text(STALE)

    lint("--fix")

    assert lint().returncode == 0, lint().stdout
