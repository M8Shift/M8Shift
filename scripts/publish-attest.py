#!/usr/bin/env python3
"""Published-base attestation for a NEW ref (#300).

A new ref is the one push shape git can give the gate no endpoint evidence for:
`remote_sha` is all zeros, so #262's fail-closed rule scans the whole reachable
history and can downgrade nothing. A repository that adopted the gate after the
fact therefore cannot publish a tag or a branch at all while any published
history carries a denied term — measured on a real release, where the refused
push would have transmitted exactly one object, the tag itself.

This helper supplies the missing evidence, and nothing else:

* It is the ONLY network-capable piece. `scripts/scrub-check.py` keeps its
  local-only spawn guard; nothing here is imported by it or callable from it.
* It is an auditable cooperative control, NOT a security boundary. Anyone able to
  rewrite Git metadata can also pass `--no-verify`. Its value is that a decision
  to publish leaves a durable, inspectable record — not that it cannot be
  circumvented. Corruption must still not become authority, so malformed,
  oversized, symlinked, permission-unsafe or checksum-bad receipts are refused.
* It never widens the scan. On success it replaces a bare-SHA range with
  `published_base..source`, the same bounded shape git hands an existing-ref
  update. The tag object, the pushed tip, paths, messages and every commit after
  the base stay scanned.

FRESHNESS IS STATE, NOT AGE. A recent timestamp would recreate #262 with a
different cache file. Creation observes the push endpoint; the hook re-observes
the SAME endpoint immediately before use; the published ref must still advertise
the EXACT same SHA and the destination must still be absent. Advance, rewind,
deletion, ambiguity or unreachability make the receipt stale whatever its age.
The 15-minute ceiling bounds replay; it is not publication authority.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time

SCHEMA = "m8shift.publish-attestation.v1"
RECEIPT_DIR = "m8shift-attest"
# Bounds replay only. A slow object upload happens AFTER the hook consumed the
# proof, so it cannot age the receipt out mid-push.
CEILING_S = 15 * 60
# A clock nudged slightly forward must not look like forgery; a clock nudged far
# forward must not buy extra life.
SKEW_S = 60
OBSERVE_TIMEOUT_S = 60
GIT_TIMEOUT_S = 30
MAX_RECEIPT_BYTES = 64 * 1024
OBJECT_RX = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")
REF_RX = re.compile(r"^refs/[A-Za-z0-9._\-/]+$")
ID_RX = re.compile(r"^[0-9a-f]{32}$")

FIELDS = frozenset({
    "schema", "receipt_id", "repo_id", "remote", "endpoint_fingerprint",
    "published_ref", "published_sha", "destination_ref", "source_sha",
    "source_commit", "observed_at", "created_at", "expires_at", "status",
    "checksum", "consumed_at", "consumed_observed_sha", "outcome",
})


class AttestationError(RuntimeError):
    """Refusal. The message is operator-facing and must name no URL or credential."""


def git(args, repo, timeout=GIT_TIMEOUT_S):
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    return proc


def git_out(args, repo, what):
    proc = git(args, repo)
    if proc.returncode != 0:
        raise AttestationError("git %s failed (rc=%d) while %s"
                               % (args[0], proc.returncode, what))
    return (proc.stdout or "").strip()


def common_dir(repo):
    path = git_out(["rev-parse", "--path-format=absolute", "--git-common-dir"],
                   repo, "resolving the repository")
    return os.path.realpath(path)


def repo_identity(repo):
    """Bind a receipt to one repository. A receipt carried elsewhere proves nothing."""
    return hashlib.sha256(common_dir(repo).encode("utf-8")).hexdigest()


def push_location(remote, repo):
    """Resolve the PUSH location, never the fetch URL.

    #262 established that `ls-remote <name>` can observe a different endpoint than
    the one a push reaches when `pushurl` is configured. Observing the wrong
    endpoint would attest a base the destination never advertised.

    V1 refuses what it cannot reason about rather than guessing: a direct URL
    instead of a configured remote, and a remote with several push URLs.
    """
    if not remote or remote.startswith("-") or "/" in remote or ":" in remote:
        raise AttestationError("v1 attests a configured remote NAME, not a URL")
    proc = git(["remote", "get-url", "--push", "--all", remote], repo)
    if proc.returncode != 0:
        raise AttestationError("unknown remote %r" % remote)
    urls = [u for u in (proc.stdout or "").splitlines() if u.strip()]
    if not urls:
        raise AttestationError("remote %r advertises no push URL" % remote)
    if len(urls) > 1:
        raise AttestationError("remote %r has %d push URLs; v1 attests exactly one"
                               % (remote, len(urls)))
    return urls[0].strip()


def fingerprint(url):
    """Identify an endpoint without ever storing or printing it."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def observe(url, published_ref, destination_ref):
    """One bounded live observation. -> published SHA.

    The only network call in the product. A timeout is not a soft failure: no
    observation means no proof.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--refs", "--", url, published_ref, destination_ref],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=OBSERVE_TIMEOUT_S,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        raise AttestationError("endpoint observation timed out; no proof")
    if proc.returncode != 0:
        raise AttestationError("endpoint unreachable or refused the observation")
    seen = {}
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and OBJECT_RX.match(parts[0]):
            seen.setdefault(parts[1], []).append(parts[0])
    if destination_ref in seen:
        raise AttestationError("destination ref already exists at the endpoint; "
                               "this attests a NEW ref only")
    shas = seen.get(published_ref) or []
    if not shas:
        raise AttestationError("published ref is not advertised by the endpoint")
    if len(set(shas)) != 1:
        raise AttestationError("published ref is ambiguous at the endpoint")
    return shas[0]


def comparable(published_sha, source_commit, repo):
    """True iff the two commits lie on one line of history, either direction.

    #300 V1 covers both shapes a clean push takes, because both transmit no
    unpublished commit history:

      published_base <= source   a NEW branch built ON the published base; the
                                 scan is base..source, exactly what git hands an
                                 existing-ref update.
      source <= published_base   a TAG of already-published history; the tag is
                                 at or behind the base and adds only its own
                                 object, which the scanner reads independently of
                                 commit history. This is the shape that opened
                                 #300, and the first cut excluded it.

    A DIVERGED source shares no line with the base: it carries commits the base
    has never seen, so it is refused and falls back to the bare-SHA scan. Kept
    identical at creation and consumption so the two cannot drift.
    """
    forward = git(["merge-base", "--is-ancestor", published_sha, source_commit],
                  repo).returncode == 0
    reverse = git(["merge-base", "--is-ancestor", source_commit, published_sha],
                  repo).returncode == 0
    return forward or reverse


def canonical(payload):
    body = {k: payload[k] for k in sorted(payload) if k != "checksum"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def receipt_dir(repo):
    path = os.path.join(common_dir(repo), RECEIPT_DIR)
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def receipt_path(repo, receipt_id):
    if not ID_RX.match(receipt_id or ""):
        raise AttestationError("malformed receipt id")
    return os.path.join(receipt_dir(repo), "%s.json" % receipt_id)


def write_receipt(path, payload):
    payload["checksum"] = hashlib.sha256(canonical(payload)).hexdigest()
    handle, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".att-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_receipt(path, repo):
    """Read a receipt, refusing anything ordinary corruption could turn into authority."""
    try:
        info = os.lstat(path)
    except OSError:
        raise AttestationError("no such receipt")
    if stat.S_ISLNK(info.st_mode):
        raise AttestationError("receipt is a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise AttestationError("receipt is not a regular file")
    if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise AttestationError("receipt is group- or world-accessible")
    if info.st_size > MAX_RECEIPT_BYTES:
        raise AttestationError("receipt exceeds the size bound")
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError, UnicodeError):
        raise AttestationError("receipt is unreadable or malformed")
    if not isinstance(payload, dict):
        raise AttestationError("receipt is not an object")
    unknown = set(payload) - FIELDS
    if unknown:
        raise AttestationError("receipt carries %d unknown field(s)" % len(unknown))
    if payload.get("schema") != SCHEMA:
        raise AttestationError("receipt schema is not %s" % SCHEMA)
    if payload.get("checksum") != hashlib.sha256(canonical(payload)).hexdigest():
        raise AttestationError("receipt checksum does not match its payload")
    if payload.get("repo_id") != repo_identity(repo):
        raise AttestationError("receipt belongs to a different repository")
    return payload


def cmd_create(args):
    repo = args.repo
    for ref, label in ((args.published_ref, "--published-ref"),
                       (args.destination_ref, "--destination-ref")):
        if not REF_RX.match(ref or ""):
            raise AttestationError("%s must be a full refs/… name" % label)
    if args.published_ref == args.destination_ref:
        raise AttestationError("published and destination refs must differ")

    source_sha = git_out(["rev-parse", "--verify", "%s^{object}" % args.source],
                         repo, "resolving --source")
    source_commit = git_out(["rev-parse", "--verify", "%s^{commit}" % args.source],
                            repo, "peeling --source to a commit")

    url = push_location(args.remote, repo)
    published_sha = observe(url, args.published_ref, args.destination_ref)

    # No implicit fetch: an object we do not have cannot be reasoned about, and
    # fetching here would hide from the operator that their checkout is behind.
    if git(["cat-file", "-e", "%s^{commit}" % published_sha], repo).returncode != 0:
        raise AttestationError(
            "the advertised published commit is absent locally; fetch it explicitly "
            "and retry")
    if not comparable(published_sha, source_commit, repo):
        raise AttestationError("the published base and --source are on divergent "
                               "histories; nothing safe to attest")

    now = time.time()
    payload = {
        "schema": SCHEMA,
        "receipt_id": secrets.token_hex(16),
        "repo_id": repo_identity(repo),
        "remote": args.remote,
        "endpoint_fingerprint": fingerprint(url),
        "published_ref": args.published_ref,
        "published_sha": published_sha,
        "destination_ref": args.destination_ref,
        "source_sha": source_sha,
        "source_commit": source_commit,
        "observed_at": now,
        "created_at": now,
        "expires_at": now + CEILING_S,
        "status": "pending",
    }
    write_receipt(receipt_path(repo, payload["receipt_id"]), payload)
    if args.json:
        print(json.dumps({"receipt_id": payload["receipt_id"],
                          "expires_in_s": CEILING_S}, sort_keys=True))
    else:
        print("attestation %s created; valid for %d minutes, single use"
              % (payload["receipt_id"], CEILING_S // 60))
        print("  published base observed on %s" % args.published_ref)
    return 0


def cmd_fingerprint(args):
    """Print the canonical push-endpoint fingerprint, never the endpoint itself.

    The pre-push public-destination declaration uses this exact resolver so
    `pushurl`, `pushInsteadOf`, endpoint changes and multi-push ambiguity cannot
    drift between the operator-facing setup command and enforcement.
    """
    print(fingerprint(push_location(args.remote, args.repo)))
    return 0


def cmd_consume(args):
    """Claim a receipt for exactly one push and re-prove it live. -> prints the base.

    Prints the attested base on success and nothing on refusal, so a caller can
    treat empty output as "no base" without parsing an error.
    """
    repo = args.repo
    path = receipt_path(repo, args.receipt_id)
    payload = read_receipt(path, repo)

    if payload.get("status") != "pending":
        raise AttestationError("receipt already consumed")
    now = time.time()
    created = float(payload.get("created_at") or 0)
    if created > now + SKEW_S:
        raise AttestationError("receipt is dated in the future")
    if now > float(payload.get("expires_at") or 0):
        raise AttestationError("receipt expired; observe again")

    if payload.get("source_sha") != args.source_sha:
        raise AttestationError("this push does not carry the attested source")
    if payload.get("destination_ref") != args.destination_ref:
        raise AttestationError("this push does not target the attested ref")

    url = push_location(payload["remote"], repo)
    if fingerprint(url) != payload.get("endpoint_fingerprint"):
        raise AttestationError("the push endpoint changed since the observation")

    # Claim BEFORE the second observation: two hooks must not both proceed, and a
    # crash after claiming costs one observation rather than allowing a replay.
    claimed = dict(payload)
    claimed["status"] = "consumed"
    claimed["consumed_at"] = now
    claimed.pop("checksum", None)
    write_receipt(path, claimed)

    observed = observe(url, payload["published_ref"], payload["destination_ref"])
    outcome = "attestation consumed"
    if observed != payload.get("published_sha"):
        outcome = "refused: published ref moved since the observation"
    elif not comparable(payload["published_sha"], payload["source_commit"], repo):
        outcome = "refused: attested base and source are on divergent histories"

    final = dict(claimed)
    final["consumed_observed_sha"] = observed
    final["outcome"] = outcome
    final.pop("checksum", None)
    write_receipt(path, final)

    if outcome != "attestation consumed":
        raise AttestationError(outcome.split(": ", 1)[1])
    print(payload["published_sha"])
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="publish-attest.py",
        description="Attest a published base so a NEW ref can be scanned as a range.")
    ap.add_argument("--repo", default=".")
    sub = ap.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="observe the endpoint and write a receipt")
    create.add_argument("--remote", required=True)
    create.add_argument("--published-ref", required=True)
    create.add_argument("--destination-ref", required=True)
    create.add_argument("--source", required=True)
    create.add_argument("--json", action="store_true")
    create.set_defaults(func=cmd_create)

    endpoint = sub.add_parser(
        "fingerprint", help="print a configured remote's push-endpoint fingerprint")
    endpoint.add_argument("--remote", required=True)
    endpoint.set_defaults(func=cmd_fingerprint)

    consume = sub.add_parser("consume", help="claim a receipt for one push")
    consume.add_argument("--receipt-id", required=True)
    consume.add_argument("--source-sha", required=True)
    consume.add_argument("--destination-ref", required=True)
    consume.set_defaults(func=cmd_consume)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except AttestationError as exc:
        print("publish-attest: %s" % exc, file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print("publish-attest: %s" % exc.__class__.__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
