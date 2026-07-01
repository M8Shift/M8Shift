#!/usr/bin/env python3
"""Regenerate the protocol reference docs (stdlib only, passive — writes only docs/).

    docs/en/protocol.md   ← m8shift.PROTOCOL["en"]            (the EN-only core)

Documentation is English-only; the i18n packs (i18n/<lang>/) still drive the localized
single-file build, but no localized docs are rendered. Run after editing the EN template
so test_protocol_docs_in_sync stays green.

    python3 scripts/gen_docs.py
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import m8shift  # noqa: E402

VERSION = "3.38.0"


def render_doc(rel, body):
    """Render embedded runtime text as repository documentation.

    The runtime core points from generated `M8SHIFT.protocol.md` to generated
    `M8SHIFT.protocol-reference.md`. In `docs/en/`, the mirror is named
    `protocol-reference.md`; keep the generated runtime files unchanged while making
    repository links navigable.
    """
    if rel == "docs/en/protocol.md":
        return body.replace("M8SHIFT.protocol-reference.md", "protocol-reference.md")
    return body


def main(argv=None):
    p = argparse.ArgumentParser(prog="gen_docs.py", description=__doc__.splitlines()[0])
    p.add_argument("--version", action="version", version=f"gen_docs.py {VERSION}")
    p.parse_args(argv)

    # (relative doc path, source text)
    targets = [
        ("docs/en/protocol.md", m8shift.PROTOCOL["en"]),
        ("docs/en/protocol-reference.md", m8shift.PROTOCOL_REFERENCE["en"]),
    ]

    for rel, body in targets:
        body = render_doc(rel, body)
        path = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"wrote {rel} ({len(body)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
