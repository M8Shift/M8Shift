#!/usr/bin/env python3
"""Regenerate the protocol reference docs from the in-file templates.

Stdlib only, passive: writes ONLY docs/en/protocol.md and docs/fr/protocole.md as exact
byte copies of m8shift.PROTOCOL['en'] / ['fr']. Run after editing the PROTOCOL templates
in m8shift.py so test_protocol_docs_in_sync stays green.

    python3 scripts/gen_docs.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import m8shift  # noqa: E402

for lang, rel in (("en", "docs/en/protocol.md"), ("fr", "docs/fr/protocole.md")):
    path = os.path.join(ROOT, rel)
    with open(path, "w", encoding="utf-8") as f:
        f.write(m8shift.PROTOCOL[lang])
    print(f"wrote {rel} ({len(m8shift.PROTOCOL[lang])} chars)")
