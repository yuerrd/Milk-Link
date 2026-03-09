from datetime import datetime
from typing import Optional

from pydantic import BaseModel, computed_field

from app.models import Period, RecordType, Unit


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
    amount_value: int
    unit: Unit
    period: Period
    fed_at: datetime

    # 向后兼容：保留 amount_ml 字段（自动包含在序列化输出中）
    @computed_field
    @property
    def amount_ml(self) -> int:
        return self.amount_value

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


class DeviceStatus(BaseModel):
    device_id: str
    online: bool                        # MQTT 最近 5 分钟内有消息 = 在线
    last_seen: Optional[datetime]       # 最后 MQTT 消息时间（UTC，内存中）
    last_record_at: Optional[datetime]  # 最后数据库记录时间
    last_record_type: Optional[RecordType]
    today_count: int                    # 今日喂奶次数
    today_total_ml: int                 # 今日喂奶总量 ml


class AdminOverview(BaseModel):
    date: str
    today_count: int
    today_total_ml: int
    devices: list[DeviceStatus]
    recent_records: list[FeedingRecordOut]


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


# ── Admin CRUD ─────────────────────────────────────────────────────────────────

class AdminRecordsResponse(BaseModel):
    """分页查询记录的响应"""
    records: list[FeedingRecordOut]
    total: int
    page: int
    page_size: int


class AdminCreateRecord(BaseModel):
    device_id: str
    record_type: RecordType
    amount_value: int
    unit: Unit
    period: Period
    fed_at: datetime          # 前端传本地时间字符串，如 "2025-01-15T14:30"


class AdminUpdateRecord(BaseModel):
    record_type: Optional[RecordType] = None
    amount_value: Optional[int] = None
    unit: Optional[Unit] = None
    period: Optional[Period] = None
    fed_at: Optional[datetime] = None
