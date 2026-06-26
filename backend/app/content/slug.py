"""Heading slug generation shared by the renderer and the chunker so anchor ids
match between rendered HTML and search results."""

from __future__ import annotations

import re


def slugify(text: str, used: set[str]) -> str:
    """Return a unique, URL-safe slug for `text`, deduping against `used`."""
    base = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "section"
    slug = base
    i = 1
    while slug in used:
        i += 1
        slug = f"{base}-{i}"
    used.add(slug)
    return slug
