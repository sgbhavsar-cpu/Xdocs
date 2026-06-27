"""Server-side markdown rendering, heading extraction, and HTML sanitization (B3).

Markdown -> safe HTML using markdown-it-py. Raw HTML passthrough is disabled and
the output is sanitized with nh3 (defense in depth) to prevent stored XSS
(design §12). Mermaid/KaTeX are left as fenced code blocks / math and rendered
client-side by the viewer (design §3.5).
"""

from __future__ import annotations

from typing import Any

import nh3
from markdown_it import MarkdownIt
from mdit_py_plugins.attrs import attrs_plugin

from app.content.slug import slugify

_HEADING_LEVELS = {"h2": 2, "h3": 3, "h4": 4}

# Image positioning: `![alt](url){align=center}` -> a safe class (no inline style).
_ALIGN_CLASS = {
    "left": "xd-img-left",
    "center": "xd-img-center",
    "right": "xd-img-right",
}

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
# `data-sl` (source line) is stamped on block elements only when render_markdown is
# called with source_map=True (the admin preview), so the editor can map a click in
# the preview back to the originating Markdown lines. Public page renders never set
# source_map, so the attribute is never emitted there even though it is allowlisted.
_ALLOWED_ATTRS: dict[str, set[str]] = {
    # nh3 manages `rel` on links itself (link_rel); listing it here is rejected.
    "a": {"href", "title"},
    # width/height/class enable author-controlled image sizing + positioning
    # (`{width=320 align=center}`); `style` is intentionally excluded (XSS).
    "img": {"src", "alt", "title", "width", "height", "class"},
    # Fenced/code blocks render the source-map attr on the inner <code>.
    "code": {"class", "data-sl"},
    "pre": {"class", "data-sl"},
    "span": {"class"},
    "div": {"class"},
    "td": {"align"},
    "th": {"align"},
    "p": {"data-sl"},
    "ul": {"data-sl"},
    "ol": {"data-sl"},
    "li": {"data-sl"},
    "blockquote": {"data-sl"},
    "table": {"data-sl"},
    "hr": {"data-sl"},
    "h1": {"id", "data-sl"},
    "h2": {"id", "data-sl"},
    "h3": {"id", "data-sl"},
    "h4": {"id", "data-sl"},
    "h5": {"id", "data-sl"},
    "h6": {"id", "data-sl"},
}

_md = (
    MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True})
    .enable(["table", "strikethrough"])
    # Allow trailing `{...}` attributes (used for image width/height/alignment).
    .use(attrs_plugin, spans=False)
)


def _apply_image_attrs(token: Any) -> None:
    """Convert an image's `align=` attribute into a safe positioning class."""
    align = token.attrGet("align")
    if align is None:
        return
    token.attrs.pop("align", None)
    cls = _ALIGN_CLASS.get(str(align).lower())
    if cls:
        existing = token.attrGet("class")
        token.attrSet("class", f"{existing} {cls}".strip() if existing else cls)


def render_markdown(
    text: str, *, source_map: bool = False
) -> tuple[str, list[dict[str, Any]]]:
    """Return (sanitized_html, headings) where headings is the H2–H4 outline.

    When ``source_map`` is true, every block-level element is stamped with a
    ``data-sl`` attribute carrying its starting line in ``text`` (from the token's
    source map). The admin preview uses this to map a click in the rendered preview
    back to the originating Markdown lines; public renders leave it off.
    """
    tokens = _md.parse(text)
    headings: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for idx, tok in enumerate(tokens):
        # Stamp block opens (nesting 1) and standalone blocks (fence/hr/code_block,
        # nesting 0) with their source line; skip inline and close tokens.
        if source_map and tok.map is not None and tok.type != "inline" and tok.nesting != -1:
            tok.attrSet("data-sl", str(tok.map[0]))
        if tok.type == "heading_open":
            inline = tokens[idx + 1] if idx + 1 < len(tokens) else None
            title = inline.content if inline is not None else ""
            slug = slugify(title, used_ids)
            tok.attrSet("id", slug)
            level = _HEADING_LEVELS.get(tok.tag)
            if level is not None:
                headings.append({"level": level, "id": slug, "text": title})
        elif tok.type == "inline" and tok.children:
            for child in tok.children:
                if child.type == "image":
                    _apply_image_attrs(child)

    raw_html = _md.renderer.render(tokens, _md.options, {})
    clean = nh3.clean(raw_html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS)
    return clean, headings
