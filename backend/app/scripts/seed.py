"""Seed the dev/demo dataset (Data Model §7).

Creates two spaces (sql-server, platform), each with a published and an internal
product version, nested books/pages, and translations: full `en`, partial `fr`,
and missing `de` (to exercise the fallback + on-the-fly translation path). Idempotent.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.render import render_markdown
from app.core.db import SessionLocal
from app.models.content import Book, Page, PageTranslation, ProductVersion, Space

_NOW = datetime(2026, 6, 1, tzinfo=UTC)

INTRO_MD = """\
# Getting Started

Welcome to the **Xdocs** demo documentation. This page exercises the renderer.

## Overview

Xdocs renders Markdown to safe HTML on the server, extracts the heading outline
for the right-hand "On this page" index, and lets the client enhance code,
diagrams, and math.

## Code

```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```

## A diagram

```mermaid
flowchart LR
  A[Author] --> B[Publish] --> C[Reader]
```

## A table

| Feature | Status |
| ------- | ------ |
| Search  | Epic C |
| Ask      | Epic D |
"""

SELECT_MD = """\
# SELECT statement

The `SELECT` statement retrieves rows from the database.

## Syntax

```sql
SELECT column_list FROM table_name WHERE predicate;
```

## Arguments

- **column_list** — the columns to return.
- **table_name** — the source table.
"""

SELECT_INTO_MD = """\
# SELECT INTO

## Creating a table

Use `SELECT INTO` to create a new table from a query result.

```sql
SELECT * INTO new_table FROM source_table WHERE 1 = 0;
```
"""

PLATFORM_MD = """\
# Platform Overview

The platform space demonstrates ACL isolation: only users with access to
`platform` can read this content.
"""


async def _get_or_create_space(session: AsyncSession, slug: str, title: str, desc: str) -> Space:
    existing = (await session.execute(select(Space).where(Space.slug == slug))).scalar_one_or_none()
    if existing:
        return existing
    space = Space(slug=slug, title=title, description=desc, default_locale="en")
    session.add(space)
    await session.flush()
    return space


def _translation(locale: str, title: str, md: str, status: str = "human") -> PageTranslation:
    html, headings = render_markdown(md)
    return PageTranslation(
        locale=locale,
        title=title,
        markdown=md,
        html_cached=html,
        headings=headings,
        translation_status=status,
        revision=1,
        published_at=_NOW,
    )


async def seed(session: AsyncSession) -> None:
    # --- sql-server space ---
    sql = await _get_or_create_space(
        session, "sql-server", "SQL Server", "Demo SQL Server documentation."
    )
    if not (
        await session.execute(select(ProductVersion).where(ProductVersion.space_id == sql.id))
    ).first():
        v2022 = ProductVersion(
            space_id=sql.id, label="2022", visibility="published", is_default=True, sort_order=2
        )
        v2019 = ProductVersion(
            space_id=sql.id, label="2019", visibility="published", is_default=False, sort_order=1
        )
        vnext = ProductVersion(
            space_id=sql.id, label="vNext", visibility="internal", is_default=False, sort_order=3
        )
        session.add_all([v2022, v2019, vnext])
        await session.flush()

        book = Book(
            space_id=sql.id,
            version_id=v2022.id,
            slug="t-sql",
            title="T-SQL Reference",
            sort_order=1,
        )
        guide = Book(
            space_id=sql.id, version_id=v2022.id, slug="guide", title="Guide", sort_order=0
        )
        session.add_all([book, guide])
        await session.flush()

        intro = Page(book_id=guide.id, slug="getting-started", sort_order=0)
        select_page = Page(book_id=book.id, slug="select", sort_order=0)
        session.add_all([intro, select_page])
        await session.flush()

        select_into = Page(
            book_id=book.id, parent_page_id=select_page.id, slug="select-into", sort_order=0
        )
        session.add(select_into)
        await session.flush()

        # Translations: en (full), fr (partial — only intro), de (missing everywhere,
        # so reading `de` exercises the fallback + auto-translate path).
        def add_translations(page_id: object, items: list[tuple[str, str, str]]) -> None:
            for loc, title, md in items:
                tr = _translation(loc, title, md)
                tr.page_id = page_id  # type: ignore[assignment]
                session.add(tr)

        add_translations(
            intro.id,
            [
                ("en", "Getting Started", INTRO_MD),
                ("fr", "Prise en main", INTRO_MD.replace("Welcome to", "Bienvenue à")),
            ],
        )
        add_translations(select_page.id, [("en", "SELECT statement", SELECT_MD)])
        add_translations(select_into.id, [("en", "SELECT INTO", SELECT_INTO_MD)])

    # --- platform space (for ACL isolation demos) ---
    platform = await _get_or_create_space(
        session, "platform", "Platform", "Platform documentation."
    )
    if not (
        await session.execute(select(ProductVersion).where(ProductVersion.space_id == platform.id))
    ).first():
        pv = ProductVersion(
            space_id=platform.id, label="1.0", visibility="published", is_default=True, sort_order=1
        )
        session.add(pv)
        await session.flush()
        pbook = Book(
            space_id=platform.id, version_id=pv.id, slug="overview", title="Overview", sort_order=0
        )
        session.add(pbook)
        await session.flush()
        ppage = Page(book_id=pbook.id, slug="overview", sort_order=0)
        session.add(ppage)
        await session.flush()
        t = _translation("en", "Platform Overview", PLATFORM_MD)
        t.page_id = ppage.id
        session.add(t)

    await session.commit()


async def main() -> None:
    async with SessionLocal() as session:
        await seed(session)
    print("[seed] done.")


if __name__ == "__main__":
    asyncio.run(main())
