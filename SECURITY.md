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

- **No network.** The core and companions never open a socket, call a provider
  API, or fetch anything. The only outbound processes are operator-adopted
  argv examples (usage adapters) and best-effort local OS notifiers/hooks —
  all host-local. This is the runtime boundary; see RFC 040 / RFC 052.
- **No daemon, no privilege.** Nothing runs as a service the tool installs
  itself, nothing needs sudo, nothing mutates `PATH`. Listener OS backends are
  opt-in and explicit.
- **No secrets stored.** Provider credentials are never written into
  `M8SHIFT.md` or any sidecar; reference adapters read them in memory and emit
  only aggregate fixtures.
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
- **ShellCheck** over the installers/hooks.
- The project's own **data-hygiene lint** (`doctor --hygiene --lint`) and,
  when a confidential denylist secret is configured, `scrub-check.py` over the
  git tip, history, and PR refs.
- **OpenSSF Scorecard** for supply-chain / posture signals.
