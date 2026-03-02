from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models import Period, RecordType


# ── Request ────────────────────────────────────────────────────────────────────

class FeedRequest(BaseModel):
    device_id: str
    secret: str


class SolidFoodRequest(BaseModel):
    device_id: str
    secret: str


# ── Response ───────────────────────────────────────────────────────────────────

class FeedingRecordOut(BaseModel):
    id: int
    device_id: str
    record_type: RecordType
    amount_ml: int
    period: Period
    fed_at: datetime

    model_config = {"from_attributes": True}


class FeedResponse(BaseModel):
    """成功记录一次喂奶返回"""
    record: FeedingRecordOut
    today_count: int        # 今日第几次喂奶
    today_total_ml: int     # 今日总量（仅喂奶）
    after_solid: bool       # 是否在辅食后喂奶（120ml）


class SolidFoodResponse(BaseModel):
    """成功记录一次辅食返回"""
    record: FeedingRecordOut


class DuplicateResponse(BaseModel):
    """5分钟内重复提交返回 409"""
    duplicate: bool = True
    last_fed_at: datetime
    wait_seconds: int       # 还需等待多少秒


class TodayStats(BaseModel):
    date: str               # YYYY-MM-DD
    count: int
    total_ml: int
    records: list[FeedingRecordOut]


class DailySummary(BaseModel):
    date: str               # YYYY-MM-DD
    count: int
    total_ml: int


class WeeklyReport(BaseModel):
    week_start: str         # YYYY-MM-DD
    week_end: str
    days: list[DailySummary]
    total_count: int
    total_ml: int
    avg_count: float
    avg_ml: float


class MonthlyReport(BaseModel):
    year: int
    month: int
    days: list[DailySummary]
    total_count: int
    total_ml: int
    avg_count: float
    avg_ml: float
