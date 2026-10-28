"""Build and validate a pinned integration candidate; never move a ref."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import prepare_objects as transport

BASE = transport.BASE
ROOT = transport.WORK
OUT = transport.EVIDENCE
HEADS = (
    "d71b073c87e3037ca0c8390fb1c3ff58edacb7c6",
    "8001ae281fbfb55dcab9c4ff8e735922a91fb8b3",
    "15f0f88d04595915794d7143091ea6e11612d0c7",
    "44bdb75280b52b25da72743d396e4dc3337b2b5e",
    "d704b32241c408a4e78929ab3d52caf4d8d64c7b",
    "aac42065f49b95c8bb7ddc6283306ade87ef1fc5",
    "6cf771d0da42e00627e7b3b56ab5a20bcfd120f6",
    "0ccacd3680494821198bcacde21f8698c2253e2a",
)
EXPECTED_TREE = "59bee2d07e12ce3cf10fcbc833117dbbd2c3c280"
TESTS = (
    "tests/test_decision_engine.py", "tests/test_routing_bridge.py",
    "tests/test_top_version_cli.py", "tests/test_append_body_file_help.py",
    "tests/test_turn_lookup_isolation.py", "tests/test_runner_argv_contract.py",
    "tests/test_lease_keeper_exit_contract.py", "tests/test_fleet_fixture_cleanup.py",
    "tests/test_m8shift.py::TestPureFunctions::test_usage_watch_stale_lock_race_has_one_winner",
    "tests/test_m8shift.py::TestAdvisoryFields::test_every_test_module_imports_the_purge_before_the_product",
    "tests/test_m8shift.py::TestChecksumManifestCoverage",
)


def git(*args, data=None):
    return subprocess.check_output(["git", *args], cwd=ROOT, input=data)


def checked_path(path):
    if path != ".github/workflows/decision-engine.yml":
        transport.check_path(path)


def prepare():
    OUT.mkdir(exist_ok=True)
    if git("rev-parse", "HEAD").decode().strip() != BASE:
        raise ValueError("integration must start from the pinned public baseline")
    manifests = set()
    for head in HEADS:
        git("fetch", "--no-tags", "--depth=1", "origin", head)
        if git("rev-parse", head).decode().strip() != head:
            raise ValueError("source commit mismatch")
        patch = git("diff", "--binary", BASE, head, "--", ".",
                    ":(exclude)checksums.sha256", ":(exclude)docs/**")
        git("apply", "--index", "--whitespace=error", "-", data=patch)
        for name in git("diff", "--name-only", BASE, head, "--", "docs").decode().splitlines():
            checked_path(name)
            after = git("show", head + ":" + name)
            exists = subprocess.run(["git", "cat-file", "-e", BASE + ":" + name],
                                    cwd=ROOT, capture_output=True).returncode == 0
            before = git("show", BASE + ":" + name) if exists else b""
            if not after.startswith(before):
                raise ValueError("non-additive documentation requires explicit reconciliation")
            path = ROOT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((path.read_bytes() if path.exists() else b"") + after[len(before):])
        for line in git("show", head + ":checksums.sha256").decode().splitlines():
            if "  " in line:
                manifests.add(line.split("  ", 1)[1])
    for name in manifests:
        path = ROOT / name
        if (Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink()
                or not path.resolve().is_relative_to(ROOT) or not path.is_file()):
            raise ValueError("unsafe checksum input")
    (ROOT / "checksums.sha256").write_text("".join(
        hashlib.sha256((ROOT / name).read_bytes()).hexdigest() + "  " + name + "\n"
        for name in sorted(manifests)))
    git("add", ".")
    git("diff", "--cached", "--check")
    tree = git("write-tree").decode().strip()
    if tree != EXPECTED_TREE:
        raise ValueError("integration differs from the locally composed exact tree: " + tree)
    env = {key: value for key, value in os.environ.items()
           if key not in ("GH_TOKEN", "GITHUB_TOKEN") and not key.startswith("M8SHIFT_")}
    commands = ([sys.executable, "-m", "pytest", "-q", *TESTS],
                ["sha256sum", "-c", "checksums.sha256"],
                [sys.executable, "m8shift.py", "doctor", "--hygiene-only", "--lint"])
    with (OUT / "integration.txt").open("w") as log:
        for command in commands:
            log.write("COMMAND " + json.dumps(command) + "\n")
            log.flush()
            subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=240)
    entries = []
    for path in git("diff", "--cached", "--name-only").decode().splitlines():
        checked_path(path)
        mode = git("ls-files", "--stage", "--", path).decode().split()[0]
        if mode not in ("100644", "100755"):
            raise ValueError("unexpected file mode")
        entries.append({"path": path, "mode": mode, "type": "blob",
                        "content": git("show", ":" + path).decode("utf-8")})
    (OUT / "integration-object.json").write_text(json.dumps({"tree": tree, "entries": entries,
        "base_tree": git("rev-parse", BASE + "^{tree}").decode().strip(), "heads": HEADS}))
    print("INTEGRATION_VALIDATED", tree, flush=True)


def publish():
    if os.environ.get("GITHUB_REPOSITORY") != transport.REPO:
        raise ValueError("wrong repository")
    obj = json.loads((OUT / "integration-object.json").read_text())
    if obj["tree"] != EXPECTED_TREE or tuple(obj["heads"]) != HEADS:
        raise ValueError("unapproved integration inputs")
    for entry in obj["entries"]:
        checked_path(entry["path"])
    tree = transport.api("trees", {"base_tree": obj["base_tree"], "tree": obj["entries"]})
    if tree["sha"] != EXPECTED_TREE:
        raise ValueError("server integration tree mismatch")
    message = ("test: compose validated advisory and backlog fixes for integrated review\n\n"
               "Exact pinned inputs: " + ", ".join(HEADS) + "\n\n"
               "Refs Forge #560 #548 #555 #540 #552 #556 #529 #561.\n"
               "Integration candidate only; no merge into main or deployment authorized.")
    commit = transport.api("commits", {"message": message, "tree": tree["sha"], "parents": [BASE]})
    result = {"commit": commit["sha"], "tree": tree["sha"], "parent": BASE,
              "refs_updated": False, "heads": HEADS}
    (OUT / "integration-commit.json").write_text(json.dumps(result, indent=2) + "\n")
    print("INTEGRATION_OBJECT", json.dumps(result), flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["prepare"]:
        prepare()
    elif sys.argv[1:] == ["publish"]:
        publish()
    else:
        raise SystemExit("expected prepare or publish")
