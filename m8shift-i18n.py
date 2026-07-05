#!/usr/bin/env python3
"""m8shift-i18n.py — build a localized m8shift.py from the EN-only core + language packs.

    m8shift-i18n.py --langs fr,es --into DIR [--name m8shift.py]   # build EN + fr + es
    m8shift-i18n.py --check fr                                      # validate a pack

The English core (m8shift.py) is the source of truth for the message KEYS and structure.
Each non-English language lives as a pack under i18n/<lang>/ (messages.json + four template
bodies). This tool splices the chosen languages into a single self-contained file; the runtime
`--lang` / `$M8SHIFT_LANG` then select among the bundled languages (fallback English).

Stdlib only. Deterministic (a rebuild from the same inputs is byte-identical).
"""
import argparse
import ast
import importlib.util
import json
import os
import re
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "m8shift.py")
PACKS_DIR = os.path.join(HERE, "i18n")
VERSION = "3.52.0"

# family -> (dict name, constant prefix, pack file, raw-string?)  — raw must match the EN constant.
FAMILIES = [
    ("PROTOCOL",   "PROTOCOL", "protocol.md", True),
    ("STANZA",     "STANZA",   "stanza.txt",  False),
    ("COWORK_TPL", "COWORK",   "seed.txt",    True),
    ("BRIDGE",     "BRIDGE",   "bridge.txt",  False),
]
PLACEHOLDERS = {  # str.format keys a body may legitimately contain (others = translator typo)
    "stanza.txt": {"begin", "end", "me", "ME", "other", "OTHER"},
}


def die(msg):
    sys.exit(f"m8shift-i18n: {msg}")


def safe_output_name(name):
    if not name or os.path.basename(name) != name or os.path.isabs(name):
        die("--name must be a plain file name, not a path")
    if os.altsep and os.altsep in name:
        die("--name must be a plain file name, not a path")
    return name


def load_core():
    src = open(CORE, encoding="utf-8").read()
    spec = importlib.util.spec_from_file_location("_m8core", CORE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return src, mod


def pack_dir(lang):
    return os.path.join(PACKS_DIR, lang)


def check_pack(lang, en_keys):
    """Validate i18n/<lang>/: keys subset of EN, four non-empty templates, safe bodies."""
    d = pack_dir(lang)
    if not os.path.isdir(d):
        die(f"pack not found: {d}")
    errs = []
    mpath = os.path.join(d, "messages.json")
    if not os.path.isfile(mpath):
        errs.append("messages.json missing")
        msgs = {}
    else:
        try:
            msgs = json.loads(open(mpath, encoding="utf-8").read())
        except Exception as e:
            errs.append(f"messages.json invalid JSON: {e}")
            msgs = {}
        unknown = sorted(set(msgs) - set(en_keys))
        if unknown:
            errs.append(f"unknown message keys (not in EN): {unknown}")
        # format-safety: a translated value must render with the EN placeholders, else the build
        # passes but tr(...).format(**kw) raises at runtime for that locale (a renamed/extra
        # placeholder or a stray brace). Validate here so a bad pack fails --check, not a user.
        for k, v in msgs.items():
            if k not in en_keys:
                continue
            en_ph = set(re.findall(r"\{(\w+)\}", en_keys[k]))
            try:
                v.format(**{p: "" for p in en_ph})
            except (KeyError, ValueError, IndexError) as e:
                errs.append(f"message {k!r} is not format-safe: {e!r}")
    for _, _, fname, _ in FAMILIES:
        p = os.path.join(d, fname)
        if not os.path.isfile(p) or not open(p, encoding="utf-8").read().strip():
            errs.append(f"{fname} missing or empty (all four templates are required)")
            continue
        body = open(p, encoding="utf-8").read()
        if '"""' in body:
            errs.append(f"{fname} contains a triple-quote sequence")
        if body and body.rstrip("\\") != body and (len(body) - len(body.rstrip("\\"))) % 2:
            errs.append(f"{fname} ends in an odd run of backslashes")
        if fname == "stanza.txt":
            # the stanza is a str.format template: structural markers come from {begin}/{end},
            # never inlined (the seed, by contrast, legitimately holds literal markers).
            if "{begin}" not in body or "{end}" not in body:
                errs.append("stanza.txt must use the {begin}/{end} marker placeholders")
            if "M8SHIFT:LOCK" in body or "M8SHIFT:STANZA" in body or "COWORK:" in body:
                errs.append("stanza.txt inlines a structural marker (use {begin}/{end})")
        # dry-render str.format templates so a stray/literal brace fails here, not at user init
        allowed = PLACEHOLDERS.get(fname)
        if allowed is not None:
            try:
                body.format(**{k: "" for k in allowed})
            except (KeyError, ValueError, IndexError) as e:
                errs.append(f"{fname} is not a safe str.format template: {e!r}")
    if errs:
        die(f"pack '{lang}' invalid:\n  - " + "\n  - ".join(errs))
    return msgs


def read_pack(lang, en_keys):
    msgs = check_pack(lang, en_keys)
    out = {"messages": msgs}
    for _, _, fname, _ in FAMILIES:
        out[fname] = open(os.path.join(pack_dir(lang), fname), encoding="utf-8").read()
    return out


def const_name(prefix, lang):
    return f"{prefix}_{lang.upper().replace('-', '_')}"


def emit_const(prefix, lang, body, raw):
    name = const_name(prefix, lang)
    q = 'r"""' if raw else '"""'
    return name, f"{name} = {q}{body}\"\"\"\n\n"


def messages_block(lang, msgs, en_keys):
    """`"<lang>": { … }` ordered to the EN key order (EN value as fallback on a missing key)."""
    lines = [f'    {json.dumps(lang)}: {{']
    for k in en_keys:
        v = msgs.get(k, en_keys[k])
        lines.append(f"        {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)},")
    lines.append("    },")
    return "\n".join(lines) + "\n"


def splice_one(src, mark, replacement, *, before=False):
    n = src.count(mark)
    if n != 1:
        die(f"expected exactly one anchor {mark!r}, found {n}")
    return src.replace(mark, (replacement + mark) if before else replacement, 1)


def build(langs, en_keys):
    src = open(CORE, encoding="utf-8").read()
    # 1. emit every <FAM>_<LANG> template constant (all languages, all families)
    new_consts = ""
    for lang in langs:
        pack = read_pack(lang, en_keys)
        for _, prefix, fname, raw in FAMILIES:
            new_consts += emit_const(prefix, lang, pack[fname], raw)[1]
    src = splice_one(src, "\nPROTOCOL = {", "\n" + new_consts.rstrip() + "\n\n", before=True)
    # 2. rewrite each family dict ONCE with all languages (incremental splicing would lose
    #    its own EN-only anchor after the first language).
    for dict_name, prefix, _, _ in FAMILIES:
        en_const = "COWORK_EN" if dict_name == "COWORK_TPL" else f"{prefix}_EN"
        items = [f'"en": {en_const}'] + [f"{json.dumps(l)}: {const_name(prefix, l)}" for l in langs]
        src = splice_one(src, f"{dict_name} = {{\"en\": {en_const}}}",
                         f"{dict_name} = {{{', '.join(items)}}}")
    # 3. MESSAGES: append each "<lang>": {...} before the closing of the MESSAGES dict
    msg_blocks = "".join(messages_block(l, read_pack(l, en_keys)["messages"], en_keys)
                         for l in langs)
    src = _append_messages(src, msg_blocks)
    return src


def _append_messages(src, msg_blocks):
    """Insert the language MESSAGES sub-dicts just before the MESSAGES closing brace."""
    needle = "MESSAGES = {"
    start = src.index(needle)
    # find the matching close brace of the MESSAGES dict
    depth, i = 0, start + len(needle) - 1
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    # i points at the closing '}' of MESSAGES (on its own line "}\n")
    line_start = src.rfind("\n", 0, i) + 1
    return src[:line_start] + msg_blocks + src[line_start:]


def main():
    ap = argparse.ArgumentParser(prog="m8shift-i18n.py", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=f"m8shift-i18n.py {VERSION}",
                    help="print the tool version and exit")
    ap.add_argument("--langs", default="", help="comma-separated language codes (e.g. fr,es)")
    ap.add_argument("--into", default=".", help="output directory")
    ap.add_argument("--name", default="m8shift.py", help="output file name")
    ap.add_argument("--check", metavar="LANG", help="validate a pack and exit")
    args = ap.parse_args()

    _, core = load_core()
    en_keys = dict(core.MESSAGES["en"])   # ordered EN keys + values (fallback)

    if args.check:
        check_pack(args.check, en_keys)
        print(f"pack '{args.check}': OK")
        return 0

    langs = sorted({c.strip() for c in args.langs.split(",") if c.strip()})
    for lang in langs:
        if lang in core.PROTOCOL:
            die(f"core already bundles '{lang}' (the EN core must be language-en-only)")
        if lang not in core.KNOWN_LANGS:
            die(f"'{lang}' is not in KNOWN_LANGS {core.KNOWN_LANGS}")

    built = build(langs, en_keys)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            compile(built, "<built>", "exec")
    except Exception as e:
        die(f"built file failed to compile cleanly: {e}")

    # round-trip: every injected constant must equal its pack body byte-for-byte
    spec = importlib.util.spec_from_loader("_m8built", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__dict__["__file__"] = CORE   # the built module reads __file__ at import (HERE)
    exec(compile(built, "<built>", "exec"), mod.__dict__)
    for lang in langs:
        pack = read_pack(lang, en_keys)
        assert mod.PROTOCOL[lang] == pack["protocol.md"], f"{lang} PROTOCOL round-trip"
        assert mod.STANZA[lang] == pack["stanza.txt"], f"{lang} STANZA round-trip"
        assert mod.COWORK_TPL[lang] == pack["seed.txt"], f"{lang} seed round-trip"
        assert mod.BRIDGE[lang] == pack["bridge.txt"], f"{lang} BRIDGE round-trip"
        for k, v in pack["messages"].items():
            assert mod.MESSAGES[lang][k] == v, f"{lang} message {k!r} round-trip"
    assert mod.LANGS == tuple(["en"] + langs), f"LANGS = {mod.LANGS}"

    out_name = safe_output_name(args.name)
    os.makedirs(args.into, exist_ok=True)
    real_into = os.path.realpath(args.into)
    out = os.path.realpath(os.path.join(real_into, out_name))
    if os.path.commonpath([real_into, out]) != real_into:
        die("output path escapes --into")
    with open(out, "w", encoding="utf-8") as f:
        f.write(built)
    os.chmod(out, 0o755)
    print(f"wrote {out}  (languages: {', '.join(['en'] + langs)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
