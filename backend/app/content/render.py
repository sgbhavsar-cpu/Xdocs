"""Server-side markdown rendering, heading extraction, and HTML sanitization (B3).

Markdown -> safe HTML using markdown-it-py. Raw HTML passthrough is disabled and
the output is sanitized with nh3 (defense in depth) to prevent stored XSS
(design §12). Mermaid/KaTeX are left as fenced code blocks / math and rendered
client-side by the viewer (design §3.5).
"""

from __future__ import annotations

import re
from typing import Any

import nh3
from markdown_it import MarkdownIt

_HEADING_LEVELS = {"h2": 2, "h3": 3, "h4": 4}

# Output allowlist. Raw HTML is already disabled in the parser; this is a second
# line of defense over the renderer's own output.
_ALLOWED_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "a",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "del",
    "code",
    "pre",
    "blockquote",
    "hr",
    "br",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "img",
    "span",
    "div",
}
_ALLOWED_ATTRS: dict[str, set[str]] = {
    # nh3 manages `rel` on links itself (link_rel); listing it here is rejected.
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "code": {"class"},
    "pre": {"class"},
    "span": {"class"},
    "div": {"class"},
    "td": {"align"},
    "th": {"align"},
    "h1": {"id"},
    "h2": {"id"},
    "h3": {"id"},
    "h4": {"id"},
    "h5": {"id"},
    "h6": {"id"},
}

_md = MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True}).enable(
    ["table", "strikethrough"]
)


def _slugify(text: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "section"
    slug = base
    i = 1
    while slug in used:
        i += 1
        slug = f"{base}-{i}"
    used.add(slug)
    return slug


def render_markdown(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Return (sanitized_html, headings) where headings is the H2–H4 outline."""
    tokens = _md.parse(text)
    headings: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for idx, tok in enumerate(tokens):
        if tok.type == "heading_open":
            inline = tokens[idx + 1] if idx + 1 < len(tokens) else None
            title = inline.content if inline is not None else ""
            slug = _slugify(title, used_ids)
            tok.attrSet("id", slug)
            level = _HEADING_LEVELS.get(tok.tag)
            if level is not None:
                headings.append({"level": level, "id": slug, "text": title})

    raw_html = _md.renderer.render(tokens, _md.options, {})
    clean = nh3.clean(raw_html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS)
    return clean, headings
