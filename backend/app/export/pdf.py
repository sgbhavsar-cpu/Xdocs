"""PDF rendering (E1).

Pluggable so tests run without a browser: the `mock` renderer returns a tiny
valid PDF; the `chromium` renderer prints HTML via headless Chromium (Playwright).
"""

from __future__ import annotations

from typing import Protocol

from app.core.config import get_settings

# A minimal but valid single-page PDF (used by the mock renderer in tests/CI).
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n"
    b"trailer<</Root 1 0 R/Size 4>>\n"
    b"startxref\n0\n%%EOF\n"
)


class PdfRenderer(Protocol):
    async def render(self, html: str) -> bytes: ...


class MockPdfRenderer:
    async def render(self, html: str) -> bytes:
        return _MINIMAL_PDF


class ChromiumPdfRenderer:
    def __init__(self, executable_path: str | None = None) -> None:
        self.executable_path = executable_path or None

    async def render(self, html: str) -> bytes:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                executable_path=self.executable_path, args=["--no-sandbox"]
            )
            try:
                page = await browser.new_page()
                await page.set_content(html, wait_until="networkidle")
                pdf = await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
                )
            finally:
                await browser.close()
        return pdf


def get_pdf_renderer() -> PdfRenderer:
    settings = get_settings()
    if settings.pdf_renderer == "chromium":
        return ChromiumPdfRenderer(settings.pdf_chromium_path or None)
    return MockPdfRenderer()
