# v4.0.0 release notes

## Version

**v4.0.0 (Generation).** Two operator-visible compatibility breaks land together:
the supported Python floor moves from 3.8 to 3.12, and the publish gate begins
reading tree entry **names**, so repositories that pushed cleanly before this
release can be refused by it. Neither is a relay-format change, but both change
what an operator can do without warning, which is what the Generation digit is
for. `update` enforces this itself: it refuses a major bump unless the operator
passes `--allow-generation-change` after review.

## Highlights

### The publish gate reads names, not only contents (#291, #295, #297)

Every scanner the pre-push hook ran matched file CONTENT — `git grep` over blob
bodies, the pickaxe counting occurrences inside blobs, and the commit-message
walk. No scan input had ever contained a tree entry name, so a denied identifier
carried by a filename or a directory published with rc 0 under enforcement.
Verified end to end against a real remote before the fix, and again after.

Three properties make the closure hold rather than move:

* **The frame cannot be forged.** Commit boundaries in the path walk are marked
  by a NUL run, not by a textual sentinel. Git forbids NUL inside a pathname and
  never emits an empty name, so no filename can imitate a boundary. An earlier
  sentinel drawn from the data's own alphabet — a literal `commit ` prefix — was
  itself a legal path prefix and merely relocated the collision it replaced.
* **Enumeration fails closed.** A path walk returning non-zero is an error, not
  an empty result. The diagnostic carries the subcommand and exit code but never
  Git's stderr, which quotes the offending path.
* **Coverage does not depend on the caller.** `--range`, `--all` and direct mode
  all enumerate paths, over the same revision universe the content and message
  walks use. A single selector serves all three, so the audit cannot answer one
  question for names and another for contents.

### An audit refuses rather than reporting on a prefix (#297)

The range-less audit requests one more commit than its window allows. Seeing that
extra commit means the window is too small to answer, and the scan returns 2
instead of a verdict. Explicit publish scopes stay complete: a push must be judged
whole, or a denied name rides in on its oldest transmitted commit.

### Publication is classified by endpoint proof (#262)

Local remote-tracking refs are a cache that outlives the remote it mirrors. The
gate no longer excludes history on their word; findings are classified against the
non-zero `remote_sha` Git obtains from the destination during push negotiation.
A downgrade requires **every** finding proven, not one — an earlier form let ten
proven history hits silence thirty unproven tag and message findings on a routine
`git push --follow-tags`.

### The kit runs on Python 3.12 (#252)

`GHSA-6w46-j5rx-g56g` / CVE-2025-71176 affects every pytest below 9.0.3 with no
8.x backport, and pytest 9 requires Python 3.10+. Remediation and the old floor
were mutually exclusive. Both installers enforce the new floor and `doctor`
reports it.

## Known work

* `--objects` remains the standalone release audit and is deliberately absent
  from the hook.
* `SECURITY.md` and `docs/en/agents-guide.md` still describe `--objects` as
  skipping identity headers; the code stopped doing so and the prose has not
  caught up.
* The `publish_scope` guard in `path_records_block()` is defence in depth: with
  the range-less audit refusing on an exhausted window, production never hands it
  a truncated record set. It must not be removed as dead code — it is what a
  future change to the refusal semantics would land against.

## Upgrade and verification

```sh
# 1. Interpreter first — the kit will not run below 3.12.
python3 --version

# 2. Update an adopted kit, from a copy of the NEW source.
python3 m8shift.py update --target <adopted-root> --allow-generation-change

# 3. Verify.
python3 m8shift.py doctor
shasum -a 256 -c checksums.sha256
```

Expect pushes that previously succeeded to be refused where a denied identifier
appears in a file or directory name. Remove or rename the path. A push whose only
change **removes** such a name is reported and does not block.
