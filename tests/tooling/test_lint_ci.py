"""tools/lint.py on the CI workflows and shell scripts."""


def test_when_a_workflow_has_a_key_github_does_not_know_lint_fails_and_names_the_file(
    repo, lint
):
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "name: CI\n"
        "on: push\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-24.04\n"
        "    stepz:\n"
        "      - run: echo hello\n"
    )

    result = lint()

    assert result.returncode != 0
    assert "ci.yml" in result.stdout


def test_when_a_shell_script_expands_a_variable_unquoted_lint_fails_and_names_the_line(
    repo, lint
):
    (repo / "tidy.sh").write_text(
        "#!/usr/bin/env bash\ntarget=$1\nrm -r $target\n"
    )

    result = lint()

    assert result.returncode != 0
    assert "tidy.sh:3:" in result.stdout


def test_when_a_workflow_step_expands_a_variable_unquoted_lint_fails(
    repo, lint
):
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "name: CI\n"
        "on: push\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-24.04\n"
        "    steps:\n"
        "      - run: rm -r $RUNNER_TEMP\n"
    )

    result = lint()

    assert result.returncode != 0
    assert "ci.yml:7:" in result.stdout
