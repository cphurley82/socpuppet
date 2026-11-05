# What CI runs, and when 🌙

This page says what socpuppet's CI runs, when it runs it, how to read what it says, and how to start the nightly run by hand. CI (continuous integration) is GitHub building and testing every change on its own machines. A **run** is one go of a workflow, the list of jobs in a file under `.github/workflows/`, and a **job** is one part of it, on one machine.

[![Nightly](https://github.com/cphurley82/socpuppet/actions/workflows/nightly.yml/badge.svg?branch=main)](https://github.com/cphurley82/socpuppet/actions/workflows/nightly.yml) [![CI](https://github.com/cphurley82/socpuppet/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/cphurley82/socpuppet/actions/workflows/ci.yml)

The two badges, here and at the top of the README, say how main's latest run of each tier went: **Nightly** the nightly tier's, **CI** the quick tier's. Click a badge for its runs, and a run for each machine's jobs.

## Three tiers

| Tier | Workflow | When | What |
|---|---|---|---|
| Quick | `.github/workflows/ci.yml` | every push to main and every pull request, in about half an hour | lint, the firmware, `test-quick` (the `quick` test preset), `qbox-quick` (the `qbox-quick` preset), clang-tidy, `coverage-quick` (the quick preset's tests, measured) and the sanitizers, all on Linux |
| 🌙 Nightly | `.github/workflows/nightly.yml` | every night, and by hand | everything else: every other boot, twister, the whole suite's coverage, QBox, the wheels (the installable Python packages) and the devcontainer on both Ubuntus, on every machine CI has, Ubuntu and macOS, Intel and Arm |
| Release | `.github/workflows/release.yml` | on the tag of a version | checks the release and builds it ([The release](development.md#the-release)) |

💡 The quick tier runs on Linux alone because GitHub runs only five Macs at a time for an account, and a pull request's Mac waited behind the nightly tier's; what breaks on a Mac alone is found that night. ⚠️ On an Intel Mac, `tools/ci.py --quick` runs the `quick-without-boots` preset in place of `quick`, since a boot of Linux takes minutes there. Its tests wait three times as long for a boot too (`patience_factor` in `socpuppet.pytest_plugin`), so a limit that would catch a script looping for ever does not catch four boots at once.

✅ The quick tier's last job, **CI passed**, waits for every other job of the tier and fails if one of them failed or was cancelled; it is the one check main's ruleset requires, so a job added to the tier blocks a merge with no change to the ruleset. A pull request lands by `gh pr merge N --auto --rebase`, which merges it once CI passed is green and the branch is up to date with main; to bring it up to date, rebase it onto main and push (or press GitHub's **Update branch** and choose rebase), and CI runs again. ⚠️ GitHub's rebase and merge writes each commit again, so the commits on main have new hashes, not the branch's.

## Starting the nightly by hand

On GitHub's site: the **Actions** tab, then **Nightly** in the list on the left, then the **Run workflow** button on the right. Leave the branch at `main` (or pick a branch to run its whole suite before it merges) and press the green **Run workflow**.

From the command line, with [GitHub's `gh`](https://cli.github.com):

```sh
gh workflow run nightly.yml                    # tonight's run, on main
gh workflow run nightly.yml --ref BRANCH       # a branch's whole suite, before it merges
gh run list --workflow nightly.yml --limit 5   # the latest runs, and how each went
gh run watch                                   # follow a run as it goes
```

## Why by hand, and the run that skips

GitHub's schedule is best effort: it has started the nightly run four to eight hours after the time it was given, and later as the weeks went on, so the results arrived around lunch rather than breakfast. So the night's run is started by hand in the evening, and the scheduled run is the backup. When the scheduled run comes along, its first job, **Anything to do tonight?** (`tools/nightly_gate.py`), asks GitHub whether a run by hand took the same commit in the last day. If one did and it passed, or is still going, the scheduled run skips everything else: it shows one green job and the rest skipped. If the run by hand failed, the scheduled run goes ahead and tries the commit again, so a failure that was the night's rather than the code's (a runner that went away, a fetch that timed out) gets a second go, and the **Nightly** badge stays red until a run passes.

The gate stays out of the way otherwise:

- A run by hand always runs.
- A run by hand that failed, timed out, was cancelled or never started does not count: only a pass, or a run still going, does.
- A quiet night with no run by hand runs as before, even on a commit an earlier night ran, because what changes outside the repository (a new `macos-latest`, a new release of something fetched) is what the nightly is also there to catch.
- A scheduled run that skipped does not count for the next night, so a quiet main is still tested every night.
- If the gate cannot ask GitHub, it says so as a warning and runs. A gate that is broken should cost a night's minutes, not a night's tests.

😄 So the scheduled run turns up in the morning, finds the stage swept and the audience gone home, and takes a bow anyway.

## Running CI's jobs here

Every job but **CI passed** and the gate is a thin wrapper around `tools/ci.py`, so the same command runs it on your machine: [Running CI's jobs here](development.md#running-cis-jobs-here).
