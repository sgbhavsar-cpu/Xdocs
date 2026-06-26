"""Markdown render + sanitize + heading extraction tests (B3 / B-03, B-05, B-17)."""

from __future__ import annotations

from app.content.render import render_markdown


def test_heading_outline_and_ids() -> None:
    html, headings = render_markdown("# Title\n\n## Syntax\n\nbody\n\n### Arguments\n")
    levels = {(h["level"], h["id"]) for h in headings}
    assert (2, "syntax") in levels
    assert (3, "arguments") in levels
    assert 'id="syntax"' in html
    # H1 is the page title and is not part of the on-this-page outline.
    assert all(h["level"] != 1 for h in headings)


def test_duplicate_headings_get_unique_ids() -> None:
    _, headings = render_markdown("## Notes\n\n## Notes\n")
    ids = [h["id"] for h in headings]
    assert ids == ["notes", "notes-2"]


def test_code_block_language_class_preserved() -> None:
    html, _ = render_markdown("```python\nx = 1\n```")
    assert "language-python" in html


def test_mermaid_left_as_code_for_client() -> None:
    html, _ = render_markdown("```mermaid\nflowchart LR\nA-->B\n```")
    assert "language-mermaid" in html  # client renders this fence


def test_table_renders() -> None:
    html, _ = render_markdown("| A | B |\n| - | - |\n| 1 | 2 |")
    assert "<table>" in html


def test_xss_is_sanitized() -> None:
    html, _ = render_markdown("<script>alert(1)</script>\n\n[x](javascript:alert(1))")
    # Raw HTML is escaped (no active <script>) and no executable javascript: href
    # survives (the unsafe link is rendered as inert text, not an anchor).
    assert "<script>" not in html
    assert 'href="javascript' not in html
    assert "<a" not in html
