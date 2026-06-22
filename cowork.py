#!/usr/bin/env python3
"""cowork.py — deprecated compatibility shim.

M8Shift's CLI is now `m8shift.py`. This thin wrapper execs it so existing
`./cowork.py …` invocations keep working byte-for-byte (same args, cwd, stdin/stdout,
return code). It must sit beside `m8shift.py`. New projects: copy `m8shift.py`.

Removal is not planned before the next major version; until then `cowork.py` and the
CoWork-named files (COWORK.md, COWORK:* markers) remain fully supported.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TARGET = os.path.join(_HERE, "m8shift.py")

if not os.path.exists(_TARGET):
    sys.exit("cowork.py is a deprecated shim for m8shift.py — copy m8shift.py beside it.")

# stderr only, so stdout stays clean for `status`/`wait` parsing
sys.stderr.write("note: `cowork.py` is deprecated — use `m8shift.py` (same arguments).\n")
os.execv(sys.executable, [sys.executable, _TARGET, *sys.argv[1:]])
