"""Split page markdown into section-sized chunks for indexing (C1).

Each chunk carries the anchor (heading id + text) of the section it belongs to,
so search results can deep-link to the exact section. Heading ids are produced
with the same slugifier as the renderer, keeping anchors consistent.
"""

from __future__ import annotations

import re
from typing import Any

from app.content.slug import slugify

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def chunk_markdown(markdown: str) -> list[dict[str, Any]]:
    """Return ordered chunks: [{ordinal, content, anchor:{heading_id, text}|None}].

    A new chunk starts at each H1/H2 boundary; deeper headings stay within the
    current chunk. The slug counter advances on every heading so ids line up with
    the rendered HTML.
    """
    used: set[str] = set()
    chunks: list[dict[str, Any]] = []
    buf: list[str] = []
    anchor: dict[str, str] | None = None
    ordinal = 0

    def flush() -> None:
        nonlocal ordinal
        content = "\n".join(buf).strip()
        if content:
            chunks.append({"ordinal": ordinal, "content": content, "anchor": anchor})
            ordinal += 1

    for line in markdown.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            slug = slugify(text, used)  # advance counter for every heading
            if level <= 2:
                flush()
                buf = [line]
                anchor = {"heading_id": slug, "text": text}
                continue
        buf.append(line)

    flush()
    return chunks
