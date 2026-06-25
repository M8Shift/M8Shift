#!/usr/bin/env python3
"""Regenerate the protocol reference docs (stdlib only, passive — writes only docs/).

    docs/en/protocol.md   ← m8shift.PROTOCOL["en"]            (the EN-only core)
    docs/fr/protocole.md  ← i18n/fr/protocol.md               (the FR pack body, byte-for-byte)

Since the core is English-only, the non-English protocol docs come straight from the packs,
never from PROTOCOL[lang]. Run after editing the EN template or a pack so
test_protocol_docs_in_sync stays green.

    python3 scripts/gen_docs.py
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import m8shift  # noqa: E402

VERSION = "3.18.3"


def main(argv=None):
    p = argparse.ArgumentParser(prog="gen_docs.py", description=__doc__.splitlines()[0])
    p.add_argument("--version", action="version", version=f"gen_docs.py {VERSION}")
    p.parse_args(argv)

    # (relative doc path, source text)
    targets = [("docs/en/protocol.md", m8shift.PROTOCOL["en"])]
    fr_pack = os.path.join(ROOT, "i18n", "fr", "protocol.md")
    if os.path.isfile(fr_pack):
        targets.append(("docs/fr/protocole.md", open(fr_pack, encoding="utf-8").read()))

    for rel, body in targets:
        path = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"wrote {rel} ({len(body)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
