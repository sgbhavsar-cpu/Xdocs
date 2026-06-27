"""Admin request schemas (API Spec §9)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class CreateSpaceReq(BaseModel):
    slug: str
    title: str
    default_locale: str = "en"
    description: str | None = None
    color: str | None = None


class UpdateSpaceReq(BaseModel):
    title: str | None = None
    description: str | None = None
    color: str | None = None
    default_locale: str | None = None


class CreateBookReq(BaseModel):
    space_id: uuid.UUID
    version_id: uuid.UUID
    slug: str
    title: str
    sort_order: int = 0


class CreateBookInSpaceReq(BaseModel):
    title: str


class UpdateBookReq(BaseModel):
    title: str


class CreateSectionReq(BaseModel):
    book_id: uuid.UUID
    title: str


class UpdateSectionReq(BaseModel):
    title: str


class CreatePageReq(BaseModel):
    book_id: uuid.UUID
    slug: str
    title: str
    locale: str = "en"
    parent_page_id: uuid.UUID | None = None
    section_id: uuid.UUID | None = None
    markdown: str = ""
    sort_order: int = 0


class UpdatePageReq(BaseModel):
    title: str | None = None
    slug: str | None = None
    locale: str = "en"


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
