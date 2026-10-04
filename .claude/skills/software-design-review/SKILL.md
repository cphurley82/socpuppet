---
name: software-design-review
description: "Review application code (not tests) for design quality: is it a good design, does it do only what the current tests demand, and does it fit the code around it. Runs in its own subagent."
argument-hint: [files or paths]
context: fork
background: false
---

# Software Design Review

Review the application code named under "Code to review" below, or if none is named, the non-test changes in the working tree at the end of this document. Read enough of the surrounding code to judge fit. Do not edit files; report only.

Review it as a senior engineer would in a thoughtful design review, using your own judgment. Weigh:

- Is this a good design? Judge it on its own terms: are responsibilities in the right place, is coupling low and the interface clear, would it still be the right shape once the rest of the agreed specifications land? Say what you would design differently and why.
- Does it do only what the tests currently demand? Flag speculative or defensive code: branches, parameters, checks, or abstractions no test exercises.
- Does it fit the concepts, naming, and conventions already in this area, or would a small refactor make it fit?
- Would a reader understand it without the commit message?

Ignore formatting and anything a linter enforces.

Report each finding with the code and a concrete suggestion. If nothing warrants a change, say so in one line; don't invent findings.

## Code to review

$ARGUMENTS

## Working tree

!`git status --porcelain`

## Diff

!`git diff HEAD`
