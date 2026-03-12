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


async def get_recent_records(db: AsyncSession, limit: int = 50) -> list[FeedingRecordOut]:
    """最近 N 条记录（所有类型，按时间倒序）"""
    result = await db.execute(
        select(FeedingRecord)
        .order_by(FeedingRecord.fed_at.desc())
        .limit(limit)
    )
    records = result.scalars().all()
    return [FeedingRecordOut.model_validate(r) for r in records]


async def get_daily_stats(db: AsyncSession, days: int = 7) -> list[DailySummary]:
    """最近 N 天每日喂奶汇总（仅 milk，按日期升序）"""
    now = datetime.now(_TZ)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(FeedingRecord)
        .where(FeedingRecord.fed_at >= start.replace(tzinfo=None))
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

    # 补全无记录的日期
    for i in range(days):
        key = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        if key not in day_map:
            day_map[key] = DailySummary(date=key, count=0, total_ml=0)

    return sorted(day_map.values(), key=lambda d: d.date)


async def get_today_device_stats(
    db: AsyncSession, device_id: str
) -> tuple[int, int]:
    """返回 (今日喂奶次数, 今日喂奶总量 ml) for given device"""
    now = datetime.now(_TZ)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    result = await db.execute(
        select(FeedingRecord)
        .where(FeedingRecord.device_id == device_id)
        .where(FeedingRecord.fed_at >= day_start.replace(tzinfo=None))
        .where(FeedingRecord.fed_at < day_end.replace(tzinfo=None))
        .where(FeedingRecord.record_type == RecordType.milk)
    )
    records = result.scalars().all()
    return len(records), sum(r.amount_ml for r in records)


async def get_all_device_ids(db: AsyncSession) -> list[str]:
    """查询数据库中所有出现过的 device_id（去重）"""
    from sqlalchemy import distinct
    result = await db.execute(select(distinct(FeedingRecord.device_id)))
    return list(result.scalars().all())


async def get_device_last_record(
    db: AsyncSession, device_id: str
) -> FeedingRecord | None:
    """查询设备最后一条记录"""
    result = await db.execute(
        select(FeedingRecord)
        .where(FeedingRecord.device_id == device_id)
        .order_by(FeedingRecord.fed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


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


async def get_records_filtered(
    db: AsyncSession,
    start_date: str | None = None,
    end_date: str | None = None,
    device_id: str | None = None,
    record_type: RecordType | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[FeedingRecordOut], int]:
    """
    根据筛选条件查询记录（支持分页）
    
    Args:
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        device_id: 设备ID筛选
        record_type: 记录类型筛选 (milk/solid)
        skip: 跳过记录数（分页）
        limit: 返回记录数（分页）
    
    Returns:
        (records, total_count) 元组
    """
    from datetime import datetime
    
    # 构建查询
    query = select(FeedingRecord)
    
    # 日期范围筛选
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=_TZ)
        query = query.where(FeedingRecord.fed_at >= start_dt.replace(tzinfo=None))
    
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=_TZ)
        query = query.where(FeedingRecord.fed_at <= end_dt.replace(tzinfo=None))
    
    # 设备ID筛选
    if device_id:
        query = query.where(FeedingRecord.device_id == device_id)
    
    # 记录类型筛选
    if record_type:
        query = query.where(FeedingRecord.record_type == record_type)
    
    # 获取总数（分页前）
    from sqlalchemy import func as sa_func
    count_query = select(sa_func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total_count = total_result.scalar() or 0
    
    # 应用分页和排序
    query = query.order_by(FeedingRecord.fed_at.desc()).offset(skip).limit(limit)
    
    # 执行查询
    result = await db.execute(query)
    records = result.scalars().all()
    
    return [FeedingRecordOut.model_validate(r) for r in records], total_count


async def get_records_by_date(
    db: AsyncSession,
    date_str: str,
    record_type: RecordType | None = None,
) -> list[FeedingRecordOut]:
    """
    查询指定日期的所有记录
    
    Args:
        date_str: 日期 (YYYY-MM-DD)
        record_type: 可选的记录类型筛选
    
    Returns:
        记录列表（按时间升序）
    """
    from datetime import datetime
    
    target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_TZ)
    day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    
    query = select(FeedingRecord).where(
        FeedingRecord.fed_at >= day_start.replace(tzinfo=None)
    ).where(
        FeedingRecord.fed_at < day_end.replace(tzinfo=None)
    )
    
    if record_type:
        query = query.where(FeedingRecord.record_type == record_type)
    
    query = query.order_by(FeedingRecord.fed_at.asc())
    
    result = await db.execute(query)
    records = result.scalars().all()
    
    return [FeedingRecordOut.model_validate(r) for r in records]
