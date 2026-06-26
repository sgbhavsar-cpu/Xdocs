"""Export request/response schemas (API Spec §7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ExportScope(BaseModel):
    type: Literal["page", "book", "space", "artifact"]
    id: str


class ExportRequest(BaseModel):
    scope: ExportScope
    locale: str = "en"


class ExportJobOut(BaseModel):
    job_id: uuid.UUID
    status: str
    url: str | None
    page_count: int
    expires_at: datetime
    error: str | None
