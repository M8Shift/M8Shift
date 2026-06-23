#!/usr/bin/env python3
"""Regenerate the protocol reference docs (stdlib only, passive — writes only docs/).

    docs/en/protocol.md   ← m8shift.PROTOCOL["en"]            (the EN-only core)
    docs/fr/protocole.md  ← i18n/fr/protocol.md               (the FR pack body, byte-for-byte)

Since the core is English-only, the non-English protocol docs come straight from the packs,
never from PROTOCOL[lang]. Run after editing the EN template or a pack so
test_protocol_docs_in_sync stays green.

    python3 scripts/gen_docs.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import m8shift  # noqa: E402

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
