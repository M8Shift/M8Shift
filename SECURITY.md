# Security policy

M8Shift is a local coordination tool with a deliberately small attack surface.
This document states what is in scope, how the tool is designed to fail safe,
and how to report a vulnerability.

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** — do not open a public
issue for anything exploitable.

- Preferred: use GitHub's **[private vulnerability reporting](https://github.com/M8Shift/M8Shift/security/advisories/new)**
  (Security tab → *Report a vulnerability*). It stays private until a fix ships.
- We aim to acknowledge a report within a few days and to credit reporters who
  want it once a fix is released.

When reporting, include the affected file/command, a minimal reproduction, and
the impact you observed. A proof-of-concept that stays local (no third-party
targets) is ideal.

## Supported versions

Only the latest tagged release and `main` receive security fixes. There is no
long-term-support branch. `X.Y.Z` releases are cut from `main`; fixes land on
`main` and in the next tag.

## Security model (what the tool guarantees)

M8Shift's charter bounds the surface — several classes of vulnerability are
out of scope by construction:

- **No network in the core and standard companions.** `m8shift.py` and the
  shipped companions never open a socket, call a provider API, or fetch
  anything. The **runtime boundary** is the operator's opt-in, disabled-by-
  default reference adapters under `examples/usage-adapters/`: one of them
  (`claude-oauth-usage.py`) *does* make an HTTPS call to the provider's own
  quota endpoint with the operator's credential — read in memory, emitted only
  as an aggregate fixture, never persisted. M8Shift runs such an adapter as a
  plain argv and reads its stdout; M8Shift itself still opens no socket. Local
  OS notifiers/hooks are host-local best-effort side effects. See RFC 040.
- **No daemon, no privilege.** Nothing runs as a service the tool installs
  itself, nothing needs sudo, nothing mutates `PATH`. Listener OS backends are
  opt-in and explicit.
- **No secrets stored.** Provider credentials are never written into
  `M8SHIFT.md` or any sidecar. The opt-in reference adapters read a credential
  in memory (e.g. from the OS keychain or an operator-pointed file) and emit
  only aggregate fixtures — they never print or persist the token.
- **Advisory companions.** Everything outside `m8shift.py`'s lock/pen is
  advisory: doctor findings, usage guards, worktree ownership, and the
  compression/context companions never gain write authority over the relay.

## Untrusted data (the real surface)

Treat the following as untrusted and validate accordingly — findings here are
in scope:

- **Relay content** (`M8SHIFT.md` bodies, tasks, memory, peer turn text): it is
  coordination *data*, never a system prompt; it cannot grant the pen, disclose
  secrets, or bypass `claim → work → append`.
- **`skills/*/SKILL.md`** and provider **adapter output**: third-party text on a
  cloned/shared repo. It is parsed and, for skills, rendered into `doctor`
  output — control-character/terminal-escape stripping and bounded, fail-open
  reads apply. (A gap here was fixed in the v3.58.0 cycle.)
- **Filesystem paths**: readers use `O_NOFOLLOW` + `fstat` regular-file checks
  and bounded reads; writers use `O_CREAT|O_EXCL|O_NOFOLLOW`. Symlink/TOCTOU
  and path-escape reports are in scope.
- **Subprocess boundaries**: adapters/runners/listeners launch argv arrays
  (never shell strings) with bounded, memory-capped output capture.

## Out of scope

- The reference `examples/` adapters running the operator's *own* local
  binaries (they are opt-in, disabled by default, and fail-open).
- Denial of service that requires the operator to run a hostile binary they
  themselves installed and enabled.
- Data-hygiene *leaks the operator introduces in their own private relay
  files* (`M8SHIFT.md`, logs) — the tool provides `doctor --hygiene` and
  `scripts/scrub-check.py` to catch these, but cannot prevent an operator from
  pasting foreign content locally.

## Automated checks

This repository runs, on every push/PR and on a schedule:

- **CodeQL** (`security-extended` + `security-and-quality`) over the Python.
- **Bandit** (Python SAST) failing on medium+ severity/confidence — the classes
  that would be real findings here: `shell=True`, `eval`/`exec`, weak hashes,
  insecure deserialisation, non-https `urlopen`. The stdlib argv/subprocess
  calls and fail-open `try/except` reads are low-severity by design and stay
  reported-but-non-blocking.
- **ShellCheck** over the installers/hooks and **actionlint** over the workflows.
- The project's own **data-hygiene lint** (`doctor --hygiene-only --lint`) and,
  when a confidential denylist secret is configured, `scrub-check.py` over the
  git tip, history, and PR refs.
- **OpenSSF Scorecard** for supply-chain / posture signals, plus **Dependabot**
  keeping the SHA-pinned GitHub Actions current.

## Local pre-commit / pre-push gate

CI is the backstop, but the cheapest place to stop a compartmentalization leak
is before it ever leaves the machine. The repo ships `hooks/pre-commit` and
`hooks/pre-push`, which run the same `doctor --hygiene-only --lint` locally —
and, at push time, `scripts/scrub-check.py` over **each pushed range** (the
commits this push actually publishes, derived from git's stdin ref updates;
deletion-only pushes skip the scan). The full-history walk stays a CI/audit
tool (`scrub-check.py` without `--range`), not a per-push tax. Install with:

    git config core.hooksPath hooks

They are **advisory by default** (warn, exit 0) so a contributor is never
hard-blocked by a false positive. Export `M8SHIFT_SCRUB_ENFORCE=1` to make a
hygiene/denylist hit **block** the commit and the push — the pre-commit hook
catches a denylisted identifier on the staged tip *before the commit object is
written*, so nothing reaches history to purge. The confidential denylist is
never committed: point `M8SHIFT_DENYLIST` at a private file (default
`~/.config/m8shift/denylist.txt`, one term per line). Matches are reported as
hashed labels — never the term, never the matched line.
