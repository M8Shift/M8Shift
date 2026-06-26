# RFC — Local notification mechanisms

**Status:** draft · **Source:** deferred from [010-rfc-runtime-patterns.md](010-rfc-runtime-patterns.md)

## Scope

Evaluate notification mechanisms that help an operator notice handoffs, stale turns, and runtime
events without turning M8Shift into a resident gateway.

Candidate mechanisms include stdout-only watch output, project-local prompt files, OS notifications,
and companion-generated exact resume prompts.

## Open design question

Which notification mechanism gives useful feedback while staying local, optional, and removable?

Subquestions:

- Should notifications be runtime-only, never core?
- What should the default be on headless/CI systems?
- Should OS notifications be opt-in because they are platform-specific?
- How do notifications avoid claiming that an interactive AI UI can be reliably awakened?

## Non-goal

No Slack/Discord/email/mobile connector in core. External channels would require a separate optional
adapter and must not become routing authority.
