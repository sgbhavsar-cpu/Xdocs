"""Pydantic response schemas for the content read API (API Spec §4)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class VersionRef(BaseModel):
    id: uuid.UUID
    label: str


class SpaceOut(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    description: str | None
    default_locale: str
    default_version: VersionRef | None
    visible_versions: list[VersionRef]


class SpaceListOut(BaseModel):
    items: list[SpaceOut]
    next_cursor: str | None = None


class TreePage(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    has_children: bool
    children: list[TreePage] = []


class TreeBook(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    pages: list[TreePage]


class TreeOut(BaseModel):
    space: str
    version: VersionRef
    locale: str
    books: list[TreeBook]


class HeadingOut(BaseModel):
    level: int
    id: str
    text: str


class PageRef(BaseModel):
    id: uuid.UUID
    title: str


class FallbackInfo(BaseModel):
    served_locale: str
    requested_locale: str
    can_auto_translate: bool


class PageOut(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    space: str
    book: str
    version: VersionRef
    locale: str
    translation_status: str
    html: str
    headings: list[HeadingOut]
    available_locales: list[str]
    fallback: FallbackInfo | None = None
    prev: PageRef | None = None
    next: PageRef | None = None
