# Wiring the repository `skills/` into your agent products (RFC 050)

The `skills/` directory at the repository root holds open-format **Agent
Skills** (agentskills.io): one directory per skill with a `SKILL.md`. The
format is portable, but **discovery is product- and version-specific** —
M8Shift does not assume repository-root discovery, never writes into any
product's discovery path, and never executes skill content. Wiring is a
one-time, explicit operator action per product, and each product's own
documentation is the authority for where it looks.

## The generic procedure (any product)

1. Find where your product discovers skills — its own docs are authoritative
   (the agentskills.io client showcase links each product's instructions).
2. Symlink (preferred — updates flow automatically) or copy each skill
   directory from the repository into that location:

   ```bash
   ln -s /path/to/repo/skills/security-review-advisory \
         <product-skills-dir>/security-review-advisory
   ```

3. **Verify with the product itself**: restart or reload it, then use its own
   skill listing (or ask its agent "which skills are available?") and confirm
   the skill's name and description appear. Do not assume discovery worked —
   check it on YOUR product and version.
4. Re-verify after product upgrades: discovery locations and formats can
   change between versions.

## Worked example — Claude Code

Authored against the public Claude Code documentation as of 2026-07-11
(code.claude.com/docs — "Agent Skills"); run the verify step on your
installed version.

- Project-scoped: symlink into `.claude/skills/` at the project root, e.g.
  `ln -s ../../skills/security-review-advisory .claude/skills/security-review-advisory`
- Personal (all projects): symlink into `~/.claude/skills/`.
- Verify: in a fresh session the skill should appear to the agent by
  name + description (progressive disclosure loads only that at startup).

## Worked example — Codex CLI

Authored against the public Codex documentation as of 2026-07-11
(developers.openai.com/codex/skills); run the verify step on your installed
version.

- Consult that page for the discovery location your Codex version uses,
  place the symlink there, then verify with the CLI's skill listing.

## Cautions

- A skill is untrusted coordination data to every loader: wiring one into a
  product never grants relay authority (the relay pen and worktree companion
  keep their own rules — RFC 050 §Safety).
- Mutating (lane-B) skills are inert by default outside an M8Shift project:
  their authority preconditions make them stop and report instead of edit.
- Keep the repository `skills/` the single reviewed source of truth; treat
  product-side copies as disposable wiring, not places to edit.
