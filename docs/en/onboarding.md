# The onboarding conductor (#378)

This document is a **bootstrap prompt**: hand it to any capable agent and the
agent installs and configures M8Shift itself, from download to launched lanes,
**without the operator typing one command line**. The agent executes; the
operator answers questions. It is a versioned repository artifact — treat a
divergence between this document and observed behavior as a defect to report,
never as room for improvisation.

## The governing principle

**No guessed path, no silent default, no unverified success.**

- Every location is **asked**, never assumed. A guessed path is paid for later:
  a lane whose runner lived in a temporary worktree died seven days after the
  choice nobody was warned about (#283).
- Every question names its **recommended default** and **what the choice
  engages** — not merely what it does.
- An absent prerequisite is a **finding stated before the first write**, never
  a mid-install failure.
- A launched lane is reported by **what was verified on disk**, never by what
  was started (#370).

The maintained interpreter is CPython **3.15.x**. Activate it before following the
sequence below. The technical 3.12 floor is a compatibility fallback, not another
maintained lane. This conductor uses the Bash installer; native PowerShell setup
remains documented separately in [Windows guidance](windows.md).

## Step 0 — the terrain, before anything is written

Fetch and run the read-only probe (it never writes; its exit code gates
everything that follows):

```sh
python3 -B scripts/onboard-probe.py --json
```

- Exit 0: proceed.
- Exit 3: **stop here**. Report every `blocking` finding to the operator
  verbatim, with the remedy the probe names (on Windows without WSL and
  without Git Bash: install WSL — preferred — or Git for Windows, reboot if
  WSL asked for it, run the probe again). Nothing has been written; say so.
- `advisory` findings are reported but do not block (a missing git keeps the
  core install viable through the Python fallbacks).

## Step 1 — where the instance lives (which is where M8Shift installs)

In the shipped topology, **the kit is installed per instance**: the install
directory and the instance directory are one and the same (#257 studies a
shared-binary alternative; it is deliberately not shipped). So this is ONE
question, asked plainly:

**“Where does this instance live?”**
Recommended default: a directory named after the instance, beside the
operator's project it will coordinate — **never inside a temporary or
generated tree** (#283: a lane pinned to a worktree died seven days later).
What the choice engages: `M8SHIFT.md`, the kit scripts, the runtime sidecars
and the turn journal all live here; moving it later is a first-class
relocation (#256), not a rename.

Also ask now: **“Will any agent run headless?”** Recommended default: yes.
What it engages: the reference lane runner is installed with the kit
(`--with-runner`), manifest-verified like everything else; answering no keeps
the kit smaller and the runner can be added later by re-running the installer
with the flag.

Then run the installer against the answered path — never a guessed one, and
**without its default init**: the installer would otherwise create a
default-roster instance before the operator has answered a single roster
question. Initialization is its own asked step (step 3).

```sh
bash install.sh --dir "<ANSWERED_INSTANCE_DIR>" --no-init --with-runner
```

Report what the installer **verified** (checksum lines, capability lines), not
just that it exited zero.

## Step 2 — a shift now, or stop here

Ask: **“Configure a shift instance now, or stop after the installation?”**
Recommended default: configure now. What stopping engages: the operator will
later run the same conductor from this step, nothing is lost.

If the operator stops: the installed directory holds the verified kit and
**no instance** — no `M8SHIFT.md`, no roster, nothing initialized. Say exactly
what remains to be done by hand (this document, from step 3), and end.

## Step 3 — name the instance and initialize the relay

Ask: **“What is the instance named?”** — engages the relay's identity in every
status surface and notification.

Initialization runs **inside** the answered instance directory (there is no
`--dir` flag: the kit initializes where it lives — report the working
directory you are about to use before running it):

```sh
cd "<ANSWERED_INSTANCE_DIR>" && python3 m8shift.py init --name "<INSTANCE_NAME>" --agents "<ROSTER>"
```

## Step 4 — roster and modes

Ask: **“Which agents compose the roster?”** and, for each agent,
**“Interactive, or headless with a runner?”** What headless engages: a
resident listener process polls the relay and spends provider budget on the
agent's turns; interactive engages nothing resident.

```sh
cd "<ANSWERED_INSTANCE_DIR>" && python3 m8shift-runtime.py providers init
```

Then write each headless agent's entry in `.m8shift/providers.json` with
values the operator confirmed — provider, **a real accessible model id**, and
the runner argv — and read the entry back to the operator before saving. The
product fails closed here by design: a lane never launches on an unset or
invalid model pin. Verify the edit before launching anything:

```sh
cd "<ANSWERED_INSTANCE_DIR>" && python3 m8shift-runtime.py providers check
```

## Step 5 — launch the lanes, and verify them

If at least one agent is headless, ask: **“Launch its lane now?”**
Recommended default: yes. What it engages: a resident process on this host,
surviving this conversation.

```sh
cd "<ANSWERED_INSTANCE_DIR>" && python3 m8shift-runtime.py listener start --agent "<AGENT>" --provider
cd "<ANSWERED_INSTANCE_DIR>" && python3 m8shift-runtime.py listener status --agent "<AGENT>" --json
```

The status JSON must show **`ALIVE` with a resident process and this
instance's relay root** for every launched lane — report those exact fields.
`listener status` exits zero even for a DEAD lane: the exit code is not the
verification, the ALIVE/resident evidence is. A lane you started but did not
observe is not a lane you report as running. If no lane is launched, state
what the operator runs later (the two commands above) and end cleanly. Durability depends on the observed backend and host session. A local fallback
is not a logout/reboot restart guarantee; report its actual lifetime separately.

## Keeping the protocol current (the second half of #378)

An instance created months ago runs a version nobody checked — the same
family as tree drift (#312) and loaded-versus-on-disk skew (#334): invisible
until someone looks. Make looking cheap and regular:

```sh
python3 -B scripts/onboard-probe.py --update-check --target "<INSTANCE_KIT_DIR>" --source "<RELEASE_SOURCE_DIR>"
```

- Exit 0 (`current`): the installed core's **bytes hash to the digest the
  source manifest pins** — equal VERSION strings alone never certify currency
  (a tampered or stale core at the right VERSION would pass a string compare).
- Exit 3 (`drift`): report the detail — version drift, or same-VERSION bytes
  that no longer match the manifest — and offer the upgrade, which is the
  documented release procedure (pause, `update --target … --source …`,
  doctor, checksums, resume), **run only on the operator's explicit yes**.
- Exit 3 (`unverifiable`): the named source has no readable manifest entry;
  the probe refuses to certify currency without byte evidence — say so.

Both paths are local and named explicitly: the probe never reaches for the
network on its own. Fetching a fresh release source is itself an operator
choice the agent asks about.

## The canonical nominal sequence

The hermetic nominal-path test extracts this block and refuses to let the
document drift from what is actually tested. Placeholders in angle brackets
are the operator's answers.

```sequence
python3 -B scripts/onboard-probe.py --json
bash install.sh --dir "<INSTANCE_DIR>" --no-init --with-runner
cd "<INSTANCE_DIR>" && python3 m8shift.py init --name "<INSTANCE_NAME>" --agents "<ROSTER>"
cd "<INSTANCE_DIR>" && python3 m8shift-runtime.py providers init
# the agent writes the operator-confirmed provider entry (step 4)
cd "<INSTANCE_DIR>" && python3 m8shift-runtime.py providers check
cd "<INSTANCE_DIR>" && python3 m8shift-runtime.py listener start --agent "<AGENT>" --provider
cd "<INSTANCE_DIR>" && python3 m8shift-runtime.py listener status --agent "<AGENT>" --json
```
