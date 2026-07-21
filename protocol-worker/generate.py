#!/usr/bin/env python3
"""Generate the self-contained protocol Worker from the canonical Markdown."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "docs" / "en" / "AGENT-EXCHANGE-PROTOCOL.md"
CANONICAL_URL = "https://protocol.m8shift.ai/"
SOURCE_LINK_BASE = "https://github.com/M8Shift/M8Shift/blob/main/docs/en/"
TITLE = "Agent Exchange Protocol"
DESCRIPTION = (
    "A tool-neutral operating contract for safe, durable coordination between "
    "two or more software agents."
)
LLMS_TEXT = "\n".join(
    (
        TITLE,
        DESCRIPTION,
        "Canonical URL: " + CANONICAL_URL,
        "Full protocol: " + CANONICAL_URL,
        "",
    )
)


CSS = """
:root {
  color-scheme: light dark;
  --paper: #f6f3ea;
  --ink: #17201d;
  --muted: #5d6762;
  --line: #c8cec8;
  --accent: #0c6b58;
  --code: #e9ece6;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #101614;
    --ink: #e7ede8;
    --muted: #a8b3ac;
    --line: #39443e;
    --accent: #69d3b5;
    --code: #1b2420;
  }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font: 17px/1.68 ui-serif, Georgia, Cambria, "Times New Roman", serif;
}
a { color: var(--accent); text-underline-offset: .18em; }
a:hover { text-decoration-thickness: 2px; }
.masthead, main, footer { width: min(920px, calc(100% - 40px)); margin-inline: auto; }
.masthead { padding: 72px 0 42px; border-bottom: 1px solid var(--line); }
.eyebrow {
  margin: 0 0 12px;
  color: var(--accent);
  font: 700 .78rem/1.2 ui-sans-serif, system-ui, sans-serif;
  letter-spacing: .15em;
  text-transform: uppercase;
}
h1, h2, h3 {
  font-family: ui-sans-serif, system-ui, sans-serif;
  letter-spacing: -.025em;
  line-height: 1.18;
}
h1 { max-width: 780px; margin: 0; font-size: clamp(2.7rem, 7vw, 5.7rem); }
.lede { max-width: 700px; margin: 22px 0 0; color: var(--muted); font-size: 1.16rem; }
.formats { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 25px; font-family: ui-sans-serif, system-ui, sans-serif; font-size: .92rem; }
main { padding: 28px 0 72px; }
article > h1:first-child { display: none; }
h2 { margin: 2.8em 0 .8em; padding-top: .35em; border-top: 1px solid var(--line); font-size: 1.7rem; }
h3 { margin: 2em 0 .6em; font-size: 1.2rem; }
p, ul { max-width: 78ch; }
li + li { margin-top: .38em; }
code, pre { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
code { padding: .1em .3em; border-radius: 4px; background: var(--code); font-size: .88em; }
pre { overflow-x: auto; margin: 1.4em 0; padding: 18px; border: 1px solid var(--line); border-radius: 8px; background: var(--code); line-height: 1.5; }
pre code { padding: 0; background: transparent; }
.table-wrap { overflow-x: auto; margin: 1.4em 0; }
table { width: 100%; border-collapse: collapse; font-family: ui-sans-serif, system-ui, sans-serif; font-size: .9rem; }
th, td { padding: 10px 12px; border: 1px solid var(--line); text-align: left; vertical-align: top; }
th { background: var(--code); }
footer { padding: 25px 0 48px; border-top: 1px solid var(--line); color: var(--muted); font-family: ui-sans-serif, system-ui, sans-serif; font-size: .85rem; }
@media (max-width: 620px) {
  body { font-size: 16px; }
  .masthead { padding-top: 44px; }
  th, td { padding: 8px; }
}
""".strip()


INLINE_RE = re.compile(r"(`[^`\n]+`|\[[^\]]+\]\([^)]+\))")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
FENCE_RE = re.compile(r"^```([A-Za-z0-9_-]*)\s*$")
TABLE_DIVIDER_RE = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+$")
SAFE_LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def csp_hash(value: str) -> str:
    raw = hashlib.sha256(value.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(raw).decode("ascii")


def resolve_link(target: str) -> str:
    if target.startswith(("https://", "http://", "mailto:", "#")):
        return target
    return SOURCE_LINK_BASE + target.lstrip("./")


def render_inline(value: str) -> str:
    parts: List[str] = []
    cursor = 0
    for match in INLINE_RE.finditer(value):
        parts.append(html.escape(value[cursor : match.start()]))
        token = match.group(0)
        if token.startswith("`"):
            parts.append("<code>" + html.escape(token[1:-1]) + "</code>")
        else:
            link_match = re.match(r"^\[([^\]]+)\]\(([^)]+)\)$", token)
            if link_match is None:
                raise ValueError("invalid inline link")
            label, target = link_match.groups()
            parts.append(
                '<a href="'
                + html.escape(resolve_link(target), quote=True)
                + '">'
                + html.escape(label)
                + "</a>"
            )
        cursor = match.end()
    parts.append(html.escape(value[cursor:]))
    return "".join(parts)


def slugify(value: str, seen: Dict[str, int]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "section"
    seen[base] = seen.get(base, 0) + 1
    return base if seen[base] == 1 else "{}-{}".format(base, seen[base])


def split_table_row(line: str) -> List[str]:
    return [part.strip() for part in line.strip().strip("|").split("|")]


def render_table(rows: Sequence[str]) -> str:
    if len(rows) < 2 or not TABLE_DIVIDER_RE.match(rows[1].strip()):
        return "\n".join("<p>{}</p>".format(render_inline(row)) for row in rows)
    header = split_table_row(rows[0])
    body = [split_table_row(row) for row in rows[2:]]
    chunks = ['<div class="table-wrap"><table><thead><tr>']
    chunks.extend("<th>{}</th>".format(render_inline(cell)) for cell in header)
    chunks.append("</tr></thead><tbody>")
    for row in body:
        chunks.append("<tr>")
        chunks.extend("<td>{}</td>".format(render_inline(cell)) for cell in row)
        chunks.append("</tr>")
    chunks.append("</tbody></table></div>")
    return "".join(chunks)


def render_markdown(markdown: str) -> str:
    lines = markdown.splitlines()
    result: List[str] = []
    seen_slugs: Dict[str, int] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        fence = FENCE_RE.match(line)
        if fence:
            language = fence.group(1)
            code_lines: List[str] = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index >= len(lines):
                raise ValueError("unterminated fenced code block")
            class_name = ""
            if language and SAFE_LANGUAGE_RE.match(language):
                class_name = ' class="language-{}"'.format(language)
            result.append(
                "<pre><code{}>{}</code></pre>".format(
                    class_name, html.escape("\n".join(code_lines))
                )
            )
            index += 1
            continue
        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            text = heading.group(2).strip()
            result.append(
                '<h{level} id="{slug}">{text}</h{level}>'.format(
                    level=level,
                    slug=slugify(text, seen_slugs),
                    text=render_inline(text),
                )
            )
            index += 1
            continue
        if line.startswith("<!--") and line.endswith("-->"):
            result.append(line)
            index += 1
            continue
        if line.startswith("|"):
            rows: List[str] = []
            while index < len(lines) and lines[index].startswith("|"):
                rows.append(lines[index])
                index += 1
            result.append(render_table(rows))
            continue
        if line.startswith("- "):
            items: List[str] = []
            current = line[2:].strip()
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if candidate.startswith("- "):
                    items.append(current)
                    current = candidate[2:].strip()
                    index += 1
                    continue
                if candidate.startswith("  ") and candidate.strip():
                    current += " " + candidate.strip()
                    index += 1
                    continue
                break
            items.append(current)
            result.append(
                "<ul>" + "".join("<li>{}</li>".format(render_inline(item)) for item in items) + "</ul>"
            )
            continue
        paragraph = [line.strip()]
        index += 1
        while index < len(lines):
            candidate = lines[index]
            if (
                not candidate.strip()
                or HEADING_RE.match(candidate)
                or FENCE_RE.match(candidate)
                or candidate.startswith(("- ", "|", "<!--"))
            ):
                break
            paragraph.append(candidate.strip())
            index += 1
        result.append("<p>{}</p>".format(render_inline(" ".join(paragraph))))
    return "\n".join(result)


def build_html(markdown: str) -> Tuple[str, str]:
    article = render_markdown(markdown)
    json_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": ["TechArticle", "APIReference"],
            "headline": TITLE,
            "description": DESCRIPTION,
            "url": CANONICAL_URL,
            "inLanguage": "en",
            "isAccessibleForFree": True,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    document = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <link rel="canonical" href="{canonical}">
  <style>{css}</style>
  <script type="application/ld+json">{json_ld}</script>
</head>
<body>
  <header class="masthead">
    <p class="eyebrow">M8Shift · Agent protocol</p>
    <h1>{title}</h1>
    <p class="lede">{description}</p>
    <nav class="formats" aria-label="Available formats">
      <a href="/protocol.md">Raw Markdown</a>
      <a href="/llms.txt">LLM discovery</a>
    </nav>
  </header>
  <main><article>{article}</article></main>
  <footer>Canonical source: <a href="{canonical}">{canonical}</a></footer>
</body>
</html>
""".format(
        title=html.escape(TITLE),
        description=html.escape(DESCRIPTION, quote=True),
        canonical=CANONICAL_URL,
        css=CSS,
        json_ld=json_ld.replace("</", "<\\/"),
        article=article,
    )
    csp = "; ".join(
        (
            "default-src 'none'",
            "style-src '{}'".format(csp_hash(CSS)),
            "script-src '{}'".format(csp_hash(json_ld.replace("</", "<\\/"))),
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        )
    )
    return document, csp


def js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_worker(markdown: str, document: str, csp: str) -> str:
    etags = {
        "markdown": '"sha256-{}"'.format(digest(markdown)),
        "html": '"sha256-{}"'.format(digest(document)),
        "llms": '"sha256-{}"'.format(digest(LLMS_TEXT)),
    }
    return """// Generated by generate.py. Do not edit by hand.
const MARKDOWN = {markdown};
const HTML = {html_document};
const LLMS = {llms};
const ETAGS = {etags};
const CACHE_CONTROL = "public, max-age=3600";
const VARY = "Accept, User-Agent";
const HTML_CSP = {csp};

function isBrowser(request) {{
  const ua = request.headers.get("User-Agent") || "";
  return /Mozilla\\/5\\.0|Chrome\\/|Chromium\\/|Firefox\\/|Safari\\/|Edg\\//i.test(ua);
}}

function etagMatches(request, etag) {{
  const header = request.headers.get("If-None-Match");
  if (!header) return false;
  return header.split(",").some((candidate) => {{
    const normalized = candidate.trim().replace(/^W\\//, "");
    return normalized === "*" || normalized === etag;
  }});
}}

function responseHeaders(contentType, etag, csp) {{
  const headers = new Headers({{
    "Cache-Control": CACHE_CONTROL,
    "Content-Language": "en",
    "Content-Type": contentType,
    "ETag": etag,
    "Referrer-Policy": "no-referrer",
    "Vary": VARY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
  }});
  if (csp) headers.set("Content-Security-Policy", csp);
  return headers;
}}

function serve(request, body, contentType, etag, csp = "default-src 'none'; frame-ancestors 'none'") {{
  const headers = responseHeaders(contentType, etag, csp);
  if (etagMatches(request, etag)) return new Response(null, {{ status: 304, headers }});
  const responseBody = request.method === "HEAD" ? null : body;
  return new Response(responseBody, {{ status: 200, headers }});
}}

export default {{
  async fetch(request) {{
    if (request.method !== "GET" && request.method !== "HEAD") {{
      return new Response("Method Not Allowed\\n", {{
        status: 405,
        headers: {{ "Allow": "GET, HEAD", "Cache-Control": "no-store" }},
      }});
    }}

    const url = new URL(request.url);
    const path = url.pathname;
    if (path === "/llms.txt") {{
      return serve(request, LLMS, "text/plain; charset=utf-8", ETAGS.llms);
    }}
    if (path.endsWith(".md")) {{
      return serve(request, MARKDOWN, "text/markdown; charset=utf-8", ETAGS.markdown);
    }}
    if (path !== "/" && path !== "/index.html") {{
      return new Response("Not Found\\n", {{ status: 404, headers: {{ "Cache-Control": "no-store" }} }});
    }}

    const accept = (request.headers.get("Accept") || "").toLowerCase();
    const wantsMarkdown = accept.includes("text/markdown");
    const wantsBrowserHtml = accept.includes("text/html") && isBrowser(request);
    if (!wantsMarkdown && wantsBrowserHtml) {{
      return serve(request, HTML, "text/html; charset=utf-8", ETAGS.html, HTML_CSP);
    }}
    return serve(request, MARKDOWN, "text/markdown; charset=utf-8", ETAGS.markdown);
  }},
}};
""".format(
        markdown=js_string(markdown),
        html_document=js_string(document),
        llms=js_string(LLMS_TEXT),
        etags=json.dumps(etags, sort_keys=True),
        csp=js_string(csp),
    )


def outputs() -> Iterable[Tuple[Path, str]]:
    markdown = SOURCE.read_text(encoding="utf-8")
    if not markdown.endswith("\n"):
        raise ValueError("canonical Markdown must end with a newline")
    document, csp = build_html(markdown)
    yield ROOT / "protocol.md", markdown
    yield ROOT / "protocol.html", document
    yield ROOT / "worker.mjs", build_worker(markdown, document, csp)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = parser.parse_args()
    stale: List[str] = []
    for path, content in outputs():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path.name)
        else:
            path.write_text(content, encoding="utf-8")
    if stale:
        print("stale generated files: " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
