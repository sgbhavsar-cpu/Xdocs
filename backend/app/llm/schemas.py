"""LLM request/response schemas (API Spec §6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str
    scope: str = "corpus"
    locale: str | None = None
    version: str | None = None
    conversation_id: str | None = None


class SummarizeTarget(BaseModel):
    type: Literal["page", "selection", "book"]
    id: str | None = None
    text: str | None = None


class SummarizeRequest(BaseModel):
    target: SummarizeTarget
    style: str = "concise"
    locale: str = "en"


class ExtractRequest(BaseModel):
    instruction: str
    scope: str = "corpus"
    locale: str | None = None
    format: str = "markdown_table"


class TranslateRequest(BaseModel):
    page_id: uuid.UUID
    target_locale: str
    source_locale: str | None = None


class FeedbackRequest(BaseModel):
    answer_id: uuid.UUID
    rating: Literal["up", "down"]
    comment: str | None = None


class ArtifactDownloads(BaseModel):
    md: str


class ArtifactOut(BaseModel):
    artifact_id: uuid.UUID
    kind: str
    markdown: str
    download: ArtifactDownloads
    expires_at: datetime


class TranslateOut(BaseModel):
    page_id: uuid.UUID
    target_locale: str
    html: str
    cached: bool
