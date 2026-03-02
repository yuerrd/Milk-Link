from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import FeedingRecord, RecordType
from app.schemas import DailySummary, FeedingRecordOut, MonthlyReport, WeeklyReport

_TZ = ZoneInfo(settings.timezone)


def _to_local(dt: datetime) -> datetime:
    """将 naive datetime（数据库存储的服务端时间）附加时区"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_TZ)
    return dt.astimezone(_TZ)


async def get_today_records(db: AsyncSession) -> list[FeedingRecordOut]:
    """今日喂奶记录（仅 milk，用于统计奶量）"""
    now = datetime.now(_TZ)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    result = await db.execute(
        select(FeedingRecord)
        .where(FeedingRecord.fed_at >= day_start.replace(tzinfo=None))
        .where(FeedingRecord.fed_at < day_end.replace(tzinfo=None))
        .where(FeedingRecord.record_type == RecordType.milk)
        .order_by(FeedingRecord.fed_at.asc())
    )
    records = result.scalars().all()
    return [FeedingRecordOut.model_validate(r) for r in records]


async def get_today_all_records(db: AsyncSession) -> list[FeedingRecordOut]:
    """今日全部记录（milk + solid），按时间排序，用于推送日报"""
    now = datetime.now(_TZ)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    result = await db.execute(
        select(FeedingRecord)
        .where(FeedingRecord.fed_at >= day_start.replace(tzinfo=None))
        .where(FeedingRecord.fed_at < day_end.replace(tzinfo=None))
        .order_by(FeedingRecord.fed_at.asc())
    )
    records = result.scalars().all()
    return [FeedingRecordOut.model_validate(r) for r in records]


async def get_week_records(db: AsyncSession) -> WeeklyReport:
    """统计上周一到上周日（最新完整周）"""
    today = date.today()
    # 最近一个完整周：上周一 ~ 上周日
    last_sunday = today - timedelta(days=today.weekday() + 1)
    last_monday = last_sunday - timedelta(days=6)

    week_start = datetime(last_monday.year, last_monday.month, last_monday.day, 0, 0, 0)
    week_end = datetime(last_sunday.year, last_sunday.month, last_sunday.day, 23, 59, 59)

    result = await db.execute(
        select(FeedingRecord)
        .where(FeedingRecord.fed_at >= week_start)
        .where(FeedingRecord.fed_at <= week_end)
        .where(FeedingRecord.record_type == RecordType.milk)
        .order_by(FeedingRecord.fed_at.asc())
    )
    records = result.scalars().all()

    day_map: dict[str, DailySummary] = {}
    for r in records:
        key = _to_local(r.fed_at).strftime("%Y-%m-%d")
        if key not in day_map:
            day_map[key] = DailySummary(date=key, count=0, total_ml=0)
        day_map[key].count += 1
        day_map[key].total_ml += r.amount_ml

    days = list(day_map.values())
    total_count = sum(d.count for d in days)
    total_ml = sum(d.total_ml for d in days)
    num_days = max(len(days), 1)

    return WeeklyReport(
        week_start=last_monday.isoformat(),
        week_end=last_sunday.isoformat(),
        days=days,
        total_count=total_count,
        total_ml=total_ml,
        avg_count=round(total_count / num_days, 1),
        avg_ml=round(total_ml / num_days, 1),
    )


async def get_month_records(db: AsyncSession) -> MonthlyReport:
    """统计上个自然月"""
    today = date.today()
    first_of_this_month = today.replace(day=1)
    last_month_end = first_of_this_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    month_start = datetime(last_month_start.year, last_month_start.month, 1, 0, 0, 0)
    month_end = datetime(last_month_end.year, last_month_end.month, last_month_end.day, 23, 59, 59)

    result = await db.execute(
        select(FeedingRecord)
        .where(FeedingRecord.fed_at >= month_start)
        .where(FeedingRecord.fed_at <= month_end)
        .where(FeedingRecord.record_type == RecordType.milk)
        .order_by(FeedingRecord.fed_at.asc())
    )
    records = result.scalars().all()

    day_map: dict[str, DailySummary] = {}
    for r in records:
        key = _to_local(r.fed_at).strftime("%Y-%m-%d")
        if key not in day_map:
            day_map[key] = DailySummary(date=key, count=0, total_ml=0)
        day_map[key].count += 1
        day_map[key].total_ml += r.amount_ml

    days = list(day_map.values())
    total_count = sum(d.count for d in days)
    total_ml = sum(d.total_ml for d in days)
    num_days = max(len(days), 1)

    return MonthlyReport(
        year=last_month_start.year,
        month=last_month_start.month,
        days=days,
        total_count=total_count,
        total_ml=total_ml,
        avg_count=round(total_count / num_days, 1),
        avg_ml=round(total_ml / num_days, 1),
    )
