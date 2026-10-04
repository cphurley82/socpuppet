---
name: tdd
description: "Implement a change with test-driven development (Canon TDD): specify, encode each spec as a test, watch it fail, fulfill it."
argument-hint: [specification]
disable-model-invocation: true
---

# Test-Driven Development

## Initial Specification

$ARGUMENTS

## The loop (Kent Beck's [Canon TDD](https://tidyfirst.substack.com/p/canon-tdd))

1. List the specifications in scope for this session, as "under scenario A, X happens; under scenario B, Y happens".
2. Encode one item as an automated test.
3. Change the code just barely enough to make the current failure go away. No speculative or defensive code: anything beyond what the failing test demands is code no test exercises.
4. Optionally refactor, but only after committing the behavior change. Never mix the two.
5. Until the list is empty, go back to 2.

## Clarifying specifications

Before writing tests: repeat my specifications back in your own words, ask me to confirm or correct, and loop until confirmed. For how to shape a spec and name its test, see [test-design-review/SKILL.md](../test-design-review/SKILL.md).

## Workflow

1. I invoke /tdd with a draft specification.
2. We clarify until we agree on the list in scope.
3. Clean the kitchen if needed (below).
4. Take the next specification and write just one test for it. Run it and confirm it fails the way the specification predicts. Don't pause for me here. A compile or import error for a symbol that doesn't exist yet is the first failure; add only the declaration needed to reach the assertion failure. Stop and tell me only if the test passes with no code change (the behavior already exists, or the test doesn't test what we think) or fails for an unrelated reason.
5. Run /test-design-review on the test and address its findings. Show me the test, the failure output, and any finding you disagreed with, and ask for approval before continuing.
6. Write only enough application code to make the failure go away. Run the test, then the project's normal test command. Run /software-design-review on the application code and address its findings. Show me the code and the green run, and ask for approval before committing.
7. Commit the behavior change. If a refactor is called for, propose it now; it goes in its own commit.
8. Back to step 4 until the list is empty. Then I provide the next specification and we start over from step 2.

### Cleaning the kitchen

Before writing a test, picture it and where it will live. If the new behavior does not slot tidily into the conceptual framework of that area of the code, and a reconceptualizing of the current behavior would make the end result more elegant, suggest it. If I approve, abandon the current change, get to a clean working state, and perform the refactoring on a new branch. Then pause and consult me and we begin again.

### Don't be sloppy

This kind of thinking is bad:

> That failure is pre-existing (unrelated to our change, it's in send_results). Our 6 new + existing tests pass. Want me to commit and push?

We don't make dinner in a dirty kitchen. On discovering a pre-existing failure: pause, stash our changes, fix it, then resume.

### Don't be lazy

This is stupid and bad:

> pytest isn't on the PATH in this environment and the project's virtualenv wasn't activated. The tests can't run here, but the change is straightforward: removed the re-tagging and made preload_app_image return the image name.

Don't abandon tests upon encountering the slightest difficulty.
