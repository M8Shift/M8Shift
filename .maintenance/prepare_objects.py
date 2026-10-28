"""One-shot checked patch transport; create Git objects, never update refs."""
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import urllib.request

REPO = "M8Shift/M8Shift"
BASE = "390b5d20bb8ce6086b66b3b30892196d594546d1"
PLAN_SHA256 = "1a2b81c740215f38760de82053b1e6f069be716ca3ccaa23c883d836ed66da04"
WORK = Path("product").resolve()
EVIDENCE = Path("evidence").resolve()
HEX = re.compile(r"[0-9a-f]{40}\Z")
ALLOWED = re.compile(r"(?:m8shift(?:-[a-z-]+)?\.py|examples/headless_runner\.py|tests/_[a-z_]+\.py|tests/test_[a-z_]+\.py|docs/en/[A-Za-z0-9_./-]+\.md|checksums\.sha256)\Z")


def git(*args, data=None):
    return subprocess.check_output(["git", *args], cwd=WORK, input=data)


def check_path(value):
    path = PurePosixPath(value)
    if not ALLOWED.fullmatch(value) or path.is_absolute() or ".." in path.parts:
        raise ValueError("patch path outside declared product scope")


def prepare():
    packed = Path(".maintenance/changes.json.gz.b64").read_text()
    raw = gzip.decompress(base64.b64decode(packed, validate=False))
    if hashlib.sha256(raw).hexdigest() != PLAN_SHA256:
        raise ValueError("patch plan digest mismatch")
    plans = json.loads(raw)
    EVIDENCE.mkdir(exist_ok=True)
    objects = []
    for plan in plans:
        if plan["base"] != BASE or not HEX.fullmatch(plan["expected_tree"]):
            raise ValueError("unapproved base or invalid tree")
        patch = plan["patch"].encode()
        if hashlib.sha256(patch).hexdigest() != plan["patch_sha256"]:
            raise ValueError("patch digest mismatch")
        git("reset", "--hard", BASE)
        git("clean", "-fd")
        git("apply", "--index", "--whitespace=error", "-", data=patch)
        git("diff", "--cached", "--check")
        tree = git("write-tree").decode().strip()
        if tree != plan["expected_tree"]:
            raise ValueError("prepared tree differs from locally verified tree")
        paths = git("diff", "--cached", "--name-only", "-z").decode().split("\0")
        paths = [value for value in paths if value]
        for path in paths:
            check_path(path)
        for test in plan["tests"]:
            if not re.fullmatch(r"tests/test_[A-Za-z0-9_]+\.py(?:::[A-Za-z0-9_]+)*", test):
                raise ValueError("unexpected test selector")
        env = {key: value for key, value in os.environ.items()
               if key not in ("GH_TOKEN", "GITHUB_TOKEN") and not key.startswith("M8SHIFT_")}
        log = EVIDENCE / (str(plan["issue"]) + ".txt")
        with log.open("w") as output:
            for command in ([sys.executable, "-m", "pytest", "-q", *plan["tests"]],
                            ["sha256sum", "-c", "checksums.sha256"],
                            [sys.executable, "m8shift.py", "doctor", "--hygiene-only", "--lint"]):
                output.write("COMMAND " + json.dumps(command) + "\n")
                output.flush()
                subprocess.run(command, cwd=WORK, env=env, stdout=output,
                               stderr=subprocess.STDOUT, check=True, timeout=180)
        entries = []
        for path in paths:
            index = git("ls-files", "--stage", "--", path).decode().strip()
            metadata, actual_path = index.split("\t", 1)
            mode, _sha, stage = metadata.split()
            if actual_path != path or mode not in ("100644", "100755") or stage != "0":
                raise ValueError("unexpected staged object")
            data = git("show", ":" + path)
            if path.endswith(".py"):
                compile(data, path, "exec")
            entries.append({"path": path, "mode": mode, "type": "blob", "content": data.decode("utf-8")})
        objects.append({"issue": plan["issue"], "base": BASE,
                        "base_tree": git("rev-parse", BASE + "^{tree}").decode().strip(),
                        "expected_tree": tree, "message": plan["message"], "entries": entries})
        print("VALIDATED", plan["issue"], tree, flush=True)
    (EVIDENCE / "objects.json").write_text(json.dumps(objects))


def api(endpoint, payload):
    if endpoint not in ("trees", "commits"):
        raise ValueError("ref updates are forbidden")
    request = urllib.request.Request(
        "https://api.github.com/repos/" + REPO + "/git/" + endpoint,
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json", "Content-Type": "application/json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def publish_objects():
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise ValueError("wrong repository")
    results = []
    for item in json.loads((EVIDENCE / "objects.json").read_text()):
        if item["base"] != BASE:
            raise ValueError("unexpected parent")
        for entry in item["entries"]:
            check_path(entry["path"])
        tree = api("trees", {"base_tree": item["base_tree"], "tree": item["entries"]})
        if tree["sha"] != item["expected_tree"]:
            raise ValueError("server tree differs from validated tree")
        commit = api("commits", {"message": item["message"], "tree": tree["sha"], "parents": [BASE]})
        results.append({"issue": item["issue"], "commit": commit["sha"], "tree": tree["sha"],
                        "parent": BASE, "refs_updated": False})
        print("CREATED_OBJECT", json.dumps(results[-1]), flush=True)
    (EVIDENCE / "commits.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["prepare"]:
        prepare()
    elif sys.argv[1:] == ["publish-objects"]:
        publish_objects()
    else:
        raise SystemExit("expected prepare or publish-objects")
