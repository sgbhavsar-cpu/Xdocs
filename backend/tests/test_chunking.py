"""Chunking tests (C1 / C-01)."""

from __future__ import annotations

from app.content.render import render_markdown
from app.search.chunking import chunk_markdown


def test_splits_by_h2_with_anchors() -> None:
    md = "# Title\n\nintro text\n\n## Syntax\n\nbody\n\n## Arguments\n\nmore"
    chunks = chunk_markdown(md)
    anchors = [c["anchor"]["heading_id"] for c in chunks if c["anchor"]]
    assert "syntax" in anchors
    assert "arguments" in anchors
    assert any("intro text" in c["content"] for c in chunks)


def test_anchor_ids_match_rendered_headings() -> None:
    md = "## Notes\n\nalpha\n\n## Notes\n\nbeta"
    _, headings = render_markdown(md)
    chunks = chunk_markdown(md)
    rendered_ids = [h["id"] for h in headings]
    chunk_ids = [c["anchor"]["heading_id"] for c in chunks if c["anchor"]]
    assert chunk_ids == rendered_ids == ["notes", "notes-2"]


def test_deeper_headings_stay_in_section() -> None:
    md = "## Section\n\n### Sub\n\ntext"
    chunks = chunk_markdown(md)
    assert len(chunks) == 1
    assert chunks[0]["anchor"]["heading_id"] == "section"
