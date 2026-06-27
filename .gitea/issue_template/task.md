---
name: "Task"
about: "A unit of work on M8Shift (issue → branch → MR → review → merge)"
title: "<type>: <short summary>"
labels: []
---

## Goal

<!-- The outcome this change delivers, in one or two sentences. -->

## Scope

- **In:**
- **Out:**

## Acceptance criteria

- [ ] Tests added/updated and green (`python3 -m unittest discover -s tests`)
- [ ] Docs updated in the same change (and the site, if this bumps the version)
- [ ]

## Charter constraints

<!-- Invariants this must respect, when relevant: stdlib-only, no daemon, no network,
     advisory companions, read-only doctor. Write N/A if none apply. -->

## Roles

- **Implementer:**
- **Reviewer:** <!-- independent — the author never green-lights their own work -->

## Workflow

`branch` → MR (`Closes #<n>`) → independent review → merge when stable → push forge-first then GitHub.

## Decision log

<!-- Record decisions, agreements, and disagreements here as the task progresses;
     close with a short wrap-up (affected branches, merged MR, final outcome). -->
