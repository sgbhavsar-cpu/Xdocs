"""Admin request schemas (API Spec §9)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class CreateSpaceReq(BaseModel):
    slug: str
    title: str
    default_locale: str = "en"


class CreateBookReq(BaseModel):
    space_id: uuid.UUID
    version_id: uuid.UUID
    slug: str
    title: str
    sort_order: int = 0


class CreatePageReq(BaseModel):
    book_id: uuid.UUID
    slug: str
    title: str
    locale: str = "en"
    parent_page_id: uuid.UUID | None = None
    markdown: str = ""
    sort_order: int = 0


class SaveTranslationReq(BaseModel):
    markdown: str
    base_revision: int | None = None
    title: str | None = None


class ReorderItem(BaseModel):
    id: str
    sort_order: int
    parent_id: str | None = None


class ReorderReq(BaseModel):
    items: list[ReorderItem]


class PreviewReq(BaseModel):
    markdown: str


class PreviewOut(BaseModel):
    html: str
    headings: list[dict]


class CreateVersionReq(BaseModel):
    space_id: uuid.UUID
    label: str
    visibility: str = "internal"
    sort_order: int = 0


class UpdateVersionReq(BaseModel):
    visibility: str | None = None
    is_default: bool | None = None


class CloneVersionReq(BaseModel):
    label: str


class DraftReq(BaseModel):
    source_locale: str = "en"
