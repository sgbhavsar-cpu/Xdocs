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


def test_image_width_and_alignment() -> None:
    html, _ = render_markdown("![cat](http://x/c.png){width=200 align=center}")
    assert 'width="200"' in html
    assert 'class="xd-img-center"' in html
    # `align` is converted to a class, not emitted as a raw attribute.
    assert "align=" not in html


def test_image_rejects_unsafe_attrs() -> None:
    # An event-handler attribute on an image must not survive (only the safe
    # width/height/class/src/alt/title attributes are allowed through).
    html, _ = render_markdown("![x](http://x/x.png){width=10 onclick=foo}")
    assert "<img" in html
    assert 'width="10"' in html
    assert "onclick" not in html


def test_source_map_stamps_block_lines() -> None:
    # With source_map=True, block elements carry a data-sl line attribute the admin
    # preview maps back to the Markdown source; the first block starts at line 0.
    html, _ = render_markdown("# Title\n\npara one\n\n- item\n", source_map=True)
    assert 'data-sl="0"' in html  # the heading
    assert 'data-sl="2"' in html  # the paragraph
    # A standalone fenced code block is stamped (on its inner <code>).
    fenced, _ = render_markdown("```\ncode\n```", source_map=True)
    assert "<pre" in fenced and 'data-sl="0"' in fenced


def test_source_map_off_by_default() -> None:
    # Public/page renders never emit data-sl, even though it is allowlisted.
    html, _ = render_markdown("# Title\n\npara\n")
    assert "data-sl" not in html


def test_xss_is_sanitized() -> None:
    html, _ = render_markdown("<script>alert(1)</script>\n\n[x](javascript:alert(1))")
    # Raw HTML is escaped (no active <script>) and no executable javascript: href
    # survives (the unsafe link is rendered as inert text, not an anchor).
    assert "<script>" not in html
    assert 'href="javascript' not in html
    assert "<a" not in html
