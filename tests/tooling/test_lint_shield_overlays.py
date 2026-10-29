"""tools/lint.py on the overlays of the Zephyr shields socpuppet makes."""

SHIELDS = "python/socpuppet/zephyr_module/boards/shields"
DRIVE = f"{SHIELDS}/socpuppet_host_drive/socpuppet_host_drive.overlay"


def test_when_a_shields_overlay_is_stale_lint_fails_and_names_the_file(
    repo, lint
):
    (repo / DRIVE).parent.mkdir(parents=True)
    (repo / DRIVE).write_text("/* Not what the host board describes. */\n")

    result = lint("shield-overlays")

    assert "❌ shield-overlays" in result.stdout
    assert DRIVE in result.stdout


def test_when_run_with_fix_a_stale_overlay_is_written_again_and_then_passes_lint(
    repo, lint
):
    (repo / DRIVE).parent.mkdir(parents=True)
    (repo / DRIVE).write_text("/* Not what the host board describes. */\n")

    lint("--fix", "shield-overlays")

    assert lint("shield-overlays").returncode == 0
