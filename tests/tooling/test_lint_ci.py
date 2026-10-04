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
