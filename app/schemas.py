from datetime import datetime
from typing import List

from pydantic import BaseModel, HttpUrl


class URLCreateRequest(BaseModel):
    url: HttpUrl
    custom_code: str | None = None  # optional vanity code


class URLResponse(BaseModel):
    short_code: str
    short_url: str
    original_url: str
    created_at: datetime

    class Config:
        from_attributes = True


class ClickEvent(BaseModel):
    timestamp: datetime
    referrer: str | None = None

    class Config:
        from_attributes = True


class StatsResponse(BaseModel):
    short_code: str
    original_url: str
    total_clicks: int
    created_at: datetime
    recent_clicks: List[ClickEvent]
