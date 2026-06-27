"""PDF -> Markdown import (F7).

Parses an uploaded PDF with pdfminer.six and turns it into one or more draft
pages' worth of Markdown:

* **Sections** follow the PDF's bookmark *outline*: each top-level (level 1)
  bookmark starts a new section/page. PDFs with no outline yield a single
  section spanning the whole document.
* **Headings** are inferred from font size — lines whose dominant glyph size is
  meaningfully larger than the document's body text become ``#``/``##``/``###``.
* **Lists** are detected from common bullet/number prefixes.
* **Images** embedded in the page stream are extracted to bytes (via pdfminer's
  ``ImageWriter``) and emitted as ``{{XDOCS_IMAGE_n}}`` placeholders inline; the
  import *service* swaps those for Markdown image references once each image has
  been persisted as a media asset.

This module is pure/sync and has no DB or web dependencies so it is easy to unit
test and cheap to run in a worker thread.
"""

from __future__ import annotations

import io
import re
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pdfminer.high_level import extract_pages
from pdfminer.image import ImageWriter
from pdfminer.layout import LTChar, LTFigure, LTTextContainer, LTTextLine
from pdfminer.layout import LTImage as _LTImage
from pdfminer.pdfdocument import PDFDocument, PDFNoOutlines
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import resolve1

_BULLET_RE = re.compile(r"^\s*([•‣⁃●▪◦•·▪‣*-]|\d{1,3}[.)])\s+")
_IMAGE_EXT_CT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
}


@dataclass
class ExtractedImage:
    name: str
    content_type: str
    data: bytes


@dataclass
class Section:
    title: str
    level: int
    markdown: str
    images: list[ExtractedImage] = field(default_factory=list)


@dataclass
class ParsedDoc:
    title: str
    sections: list[Section]


# --------------------------------------------------------------------------- #
# Outline (bookmarks) -> page boundaries
# --------------------------------------------------------------------------- #


def _page_index_by_id(doc: PDFDocument) -> dict[int, int]:
    return {page.pageid: i for i, page in enumerate(PDFPage.create_pages(doc))}


def _key(name: object) -> str | None:
    if isinstance(name, bytes):
        return name.decode("latin-1", "ignore")
    if isinstance(name, str):
        return name
    el = getattr(name, "name", None)  # PSLiteral
    return el if isinstance(el, str) else None


def _walk_name_tree(node: object, out: dict[str, object]) -> None:
    node = resolve1(node)
    if not isinstance(node, dict):
        return
    names = resolve1(node.get("Names"))
    if isinstance(names, list):
        for i in range(0, len(names) - 1, 2):
            k = _key(names[i])
            if k is not None:
                out[k] = resolve1(names[i + 1])
    for kid in resolve1(node.get("Kids")) or []:
        _walk_name_tree(kid, out)


def _named_dests(doc: PDFDocument) -> dict[str, object]:
    """Collect named destinations from both /Dests (PDF 1.1) and the
    /Names -> /Dests name tree (PDF 1.2+)."""
    out: dict[str, object] = {}
    cat = doc.catalog
    legacy = resolve1(cat.get("Dests"))
    if isinstance(legacy, dict):
        for k, v in legacy.items():
            out[k] = resolve1(v)
    names = resolve1(cat.get("Names"))
    if isinstance(names, dict):
        _walk_name_tree(names.get("Dests"), out)
    return out


def _dest_to_array(target: object, named: dict[str, object]) -> object:
    """Reduce a destination (explicit array, named string, or {/D: array}) to its
    explicit array form."""
    target = resolve1(target)
    name = _key(target)
    if name is not None and name in named:
        target = named[name]
    target = resolve1(target)
    if isinstance(target, dict):  # {/D: [...]}
        target = resolve1(target.get("D"))
    return target


def _dest_page_index(
    dest: object, action: object, by_id: dict[int, int], named: dict[str, object]
) -> int | None:
    """Resolve an outline destination (or GoTo action) to a 0-based page index."""
    target = dest
    if target is None and isinstance(action, dict):
        target = action.get("D")
    target = _dest_to_array(target, named)
    if isinstance(target, (list, tuple)) and target:
        objid = getattr(target[0], "objid", None)
        if objid is not None and objid in by_id:
            return by_id[objid]
    return None


def _top_level_sections(doc: PDFDocument) -> list[tuple[str, int]]:
    """Return [(title, page_index)] for level-1 bookmarks, ordered by page."""
    try:
        outlines = list(doc.get_outlines())
    except PDFNoOutlines:
        return []
    except Exception:  # noqa: BLE001 - malformed outlines shouldn't fail the import
        return []
    by_id = _page_index_by_id(doc)
    named = _named_dests(doc)
    out: list[tuple[str, int]] = []
    for level, title, dest, action, _se in outlines:
        if level != 1:
            continue
        idx = _dest_page_index(dest, action, by_id, named)
        if idx is not None and title:
            out.append((str(title).strip(), idx))
    out.sort(key=lambda t: t[1])
    return out


# --------------------------------------------------------------------------- #
# Layout -> Markdown
# --------------------------------------------------------------------------- #


def _line_size(line: LTTextLine) -> float:
    sizes = [round(o.size, 1) for o in line if isinstance(o, LTChar)]
    if not sizes:
        return 0.0
    # Dominant (most common) glyph size is more robust than the mean for a line
    # that mixes a heading with a trailing footnote marker, etc.
    return Counter(sizes).most_common(1)[0][0]


def _body_size(pages_layout: list) -> float:
    """Estimate the body-text font size as the size carrying the most characters.

    Weighting by character count (rather than a plain median over lines) keeps the
    estimate anchored to running prose even in documents that are mostly headings,
    so heading detection stays stable on short inputs."""
    weight: Counter[float] = Counter()
    for page in pages_layout:
        for el in page:
            if isinstance(el, LTTextContainer):
                for line in el:
                    if isinstance(line, LTTextLine):
                        s = _line_size(line)
                        if s:
                            weight[s] += max(1, len(line.get_text().strip()))
    return weight.most_common(1)[0][0] if weight else 12.0


def _heading_level(size: float, body: float) -> int:
    """0 = not a heading; otherwise Markdown heading level (1..3)."""
    if body <= 0:
        return 0
    ratio = size / body
    if ratio >= 1.7:
        return 1
    if ratio >= 1.35:
        return 2
    if ratio >= 1.15:
        return 3
    return 0


def _line_to_markdown(text: str, level: int) -> str:
    text = text.strip()
    if not text:
        return ""
    if level:
        return f"{'#' * level} {text}"
    m = _BULLET_RE.match(text)
    if m:
        return f"- {text[m.end():].strip()}"
    return text


def _page_markdown(
    page_layout, body: float, images: list[ExtractedImage], writer: ImageWriter, tmp: Path
) -> str:
    """Render one page's text+images to Markdown, appending extracted images to
    ``images`` and emitting an inline ``{{XDOCS_IMAGE_n}}`` placeholder for each."""
    blocks: list[str] = []
    # Top-to-bottom: pdfminer y grows upward, so sort by -y0.
    elements = sorted(page_layout, key=lambda e: -getattr(e, "y0", 0.0))
    for el in elements:
        if isinstance(el, LTTextContainer):
            lines: list[str] = []
            for line in el:
                if not isinstance(line, LTTextLine):
                    continue
                raw = line.get_text().strip()
                if not raw:
                    continue
                lines.append(_line_to_markdown(raw, _heading_level(_line_size(line), body)))
            if lines:
                blocks.append(_join_lines(lines))
        else:
            img = _extract_image(el, writer, tmp)
            if img is not None:
                blocks.append(f"{{{{XDOCS_IMAGE_{len(images)}}}}}")
                images.append(img)
    return "\n\n".join(b for b in blocks if b)


def _join_lines(lines: list[str]) -> str:
    """Group a text container's lines: consecutive list items / headings stay on
    their own line; runs of plain prose join into one paragraph."""
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append(" ".join(buf))
            buf.clear()

    for ln in lines:
        if ln.startswith(("#", "- ")):
            flush()
            out.append(ln)
        else:
            buf.append(ln)
    flush()
    return "\n\n".join(out)


def _extract_image(el: object, writer: ImageWriter, tmp: Path) -> ExtractedImage | None:
    """Find an image within a layout element and export its bytes. Returns None
    for non-images or formats pdfminer cannot decode."""
    image = el if isinstance(el, _LTImage) else None
    if image is None and isinstance(el, LTFigure):
        for child in el:
            if isinstance(child, _LTImage):
                image = child
                break
    if image is None:
        return None
    try:
        name = writer.export_image(image)  # writes into tmp, returns filename
    except Exception:  # noqa: BLE001 - skip undecodable images rather than fail import
        return None
    path = tmp / name
    try:
        data = path.read_bytes()
    except OSError:
        return None
    ext = path.suffix.lower()
    ct = _IMAGE_EXT_CT.get(ext)
    if ct is None:  # unsupported raw format (e.g. .img / CMYK) — skip
        return None
    return ExtractedImage(name=name, content_type=ct, data=data)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def _doc_title(doc: PDFDocument, fallback: str) -> str:
    for info in doc.info or []:
        title = info.get("Title")
        if isinstance(title, bytes):
            try:
                title = title.decode("utf-16" if title.startswith(b"\xfe\xff") else "latin-1")
            except Exception:  # noqa: BLE001
                title = None
        if title:
            return str(title).strip()
    return fallback


def parse_pdf(data: bytes, filename: str = "document.pdf") -> ParsedDoc:
    """Parse PDF bytes into a titled list of sections (one per top-level bookmark,
    or a single section when the document has no outline)."""
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    fallback = stem or "Imported document"

    doc = PDFDocument(PDFParser(io.BytesIO(data)))
    doc_title = _doc_title(doc, fallback)
    boundaries = _top_level_sections(doc)

    pages_layout = list(extract_pages(io.BytesIO(data)))
    body = _body_size(pages_layout)

    with tempfile.TemporaryDirectory(prefix="xdocs-pdf-") as tmpdir:
        tmp = Path(tmpdir)
        writer = ImageWriter(tmpdir)
        page_md: list[str] = []
        page_images: list[list[ExtractedImage]] = []
        for layout in pages_layout:
            imgs: list[ExtractedImage] = []
            page_md.append(_page_markdown(layout, body, imgs, writer, tmp))
            page_images.append(imgs)

    return _assemble(doc_title, boundaries, page_md, page_images)


def _assemble(
    doc_title: str,
    boundaries: list[tuple[str, int]],
    page_md: list[str],
    page_images: list[list[ExtractedImage]],
) -> ParsedDoc:
    n = len(page_md)
    if not boundaries:
        md = _renumber_images("\n\n".join(m for m in page_md if m))
        images = [img for imgs in page_images for img in imgs]
        return ParsedDoc(title=doc_title, sections=[Section(doc_title, 1, md, images)])

    # Pages before the first bookmark fold into a leading "front matter" prefix
    # on the first section so no content is dropped.
    first = boundaries[0][1]
    lead = "\n\n".join(m for m in page_md[:first] if m)

    sections: list[Section] = []
    for i, (title, start) in enumerate(boundaries):
        end = boundaries[i + 1][1] if i + 1 < len(boundaries) else n
        body_md = "\n\n".join(m for m in page_md[start:end] if m)
        imgs = [img for p in range(start, end) for img in page_images[p]]
        if i == 0 and lead:
            body_md = f"{lead}\n\n{body_md}" if body_md else lead
            imgs = [img for p in range(0, first) for img in page_images[p]] + imgs
        body_md = _drop_leading_title(body_md, title)
        md = _renumber_images(f"# {title}\n\n{body_md}".rstrip())
        sections.append(Section(title=title, level=1, markdown=md, images=imgs))
    return ParsedDoc(title=doc_title, sections=sections)


def _drop_leading_title(body_md: str, title: str) -> str:
    """If the section body opens with a heading that just repeats the bookmark
    title, drop it — the section already gets a single ``# title`` heading."""
    norm = title.strip().lower()
    blocks = body_md.split("\n\n")
    while blocks:
        first = blocks[0].strip()
        if first.startswith("#") and first.lstrip("# ").strip().lower() == norm:
            blocks.pop(0)
        else:
            break
    return "\n\n".join(blocks).strip()


def _renumber_images(markdown: str) -> str:
    """Image placeholders are emitted with document-global indices while a page is
    rendered, but each section persists its own image list starting at 0. Rewrite
    the placeholders in document order to 0..k for the section that owns them."""
    counter = {"i": 0}

    def repl(_m: re.Match) -> str:
        idx = counter["i"]
        counter["i"] += 1
        return f"{{{{XDOCS_IMAGE_{idx}}}}}"

    return re.sub(r"\{\{XDOCS_IMAGE_\d+\}\}", repl, markdown)
