from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import FeedingRecord, Period, RecordType
from app.schemas import DuplicateResponse, FeedResponse, FeedingRecordOut, SolidFoodResponse
from app.services.reports import get_today_records, get_today_all_records
from app.services.wechat import send_daily_report

_TZ = ZoneInfo(settings.timezone)


def _is_night(now: datetime) -> bool:
    """判断当前时间是否处于夜晚时段"""
    return settings.night_start_hour <= now.hour < settings.night_end_hour


async def record_feeding(
    db: AsyncSession,
    device_id: str,
) -> FeedResponse | DuplicateResponse:
    now_local = datetime.now(_TZ)
    now_naive = now_local.replace(tzinfo=None)

    # ── 1. 防重复：查最近一条记录 ─────────────────────────────────────────────
    result = await db.execute(
        select(FeedingRecord)
        .where(FeedingRecord.device_id == device_id)
        .order_by(FeedingRecord.fed_at.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()

    if last is not None and last.record_type == RecordType.milk:
        debounce_cutoff = now_naive - timedelta(minutes=settings.debounce_minutes)
        if last.fed_at >= debounce_cutoff:
            elapsed_seconds = int((now_naive - last.fed_at).total_seconds())
            wait_seconds = settings.debounce_minutes * 60 - elapsed_seconds
            last_fed_at_local = last.fed_at.replace(tzinfo=_TZ)
            return DuplicateResponse(
                last_fed_at=last_fed_at_local,
                wait_seconds=max(wait_seconds, 0),
            )

    # ── 2. 判断奶量：辅食后喂奶固定 120ml，否则按时段 ─────────────────────────
    after_solid = (last is not None and last.record_type == RecordType.solid)
    if after_solid:
        amount_ml = 120
        period = Period.night if _is_night(now_local) else Period.day
    else:
        period = Period.night if _is_night(now_local) else Period.day
        amount_ml = settings.night_amount_ml if period == Period.night else settings.day_amount_ml

    # ── 3. 写库 ───────────────────────────────────────────────────────────────
    new_record = FeedingRecord(
        device_id=device_id,
        record_type=RecordType.milk,
        amount_ml=amount_ml,
        period=period,
        fed_at=now_naive,
    )
    db.add(new_record)
    await db.flush()
    await db.refresh(new_record)

    # ── 4. 查今日喂奶记录（仅 milk，用于统计）────────────────────────────────
    today_records = await get_today_records(db)
    today_count = len(today_records)
    today_total_ml = sum(r.amount_ml for r in today_records)

    # ── 5. 查今日全部记录（milk + solid），推送合并日报 ────────────────────────
    today_str = now_local.strftime("%Y-%m-%d")
    all_records = await get_today_all_records(db)
    await send_daily_report(all_records, today_str)

    return FeedResponse(
        record=FeedingRecordOut.model_validate(new_record),
        today_count=today_count,
        today_total_ml=today_total_ml,
        after_solid=after_solid,
    )


async def record_solid_food(
    db: AsyncSession,
    device_id: str,
) -> SolidFoodResponse | DuplicateResponse:
    now_local = datetime.now(_TZ)
    now_naive = now_local.replace(tzinfo=None)

    # ── 防重复：2 分钟内重复按视为误触 ───────────────────────────────────────
    result = await db.execute(
        select(FeedingRecord)
        .where(FeedingRecord.device_id == device_id)
        .where(FeedingRecord.record_type == RecordType.solid)
        .order_by(FeedingRecord.fed_at.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()

    if last is not None:
        debounce_cutoff = now_naive - timedelta(minutes=2)
        if last.fed_at >= debounce_cutoff:
            elapsed_seconds = int((now_naive - last.fed_at).total_seconds())
            wait_seconds = 120 - elapsed_seconds
            last_fed_at_local = last.fed_at.replace(tzinfo=_TZ)
            return DuplicateResponse(
                last_fed_at=last_fed_at_local,
                wait_seconds=max(wait_seconds, 0),
            )

    # ── 写库（辅食不记奶量，amount_ml=0）─────────────────────────────────────
    period = Period.night if _is_night(now_local) else Period.day
    new_record = FeedingRecord(
        device_id=device_id,
        record_type=RecordType.solid,
        amount_ml=0,
        period=period,
        fed_at=now_naive,
    )
    db.add(new_record)
    await db.flush()
    await db.refresh(new_record)

    # ── 推送合并日报 ──────────────────────────────────────────────────────────
    today_str = now_local.strftime("%Y-%m-%d")
    all_records = await get_today_all_records(db)
    await send_daily_report(all_records, today_str)

    return SolidFoodResponse(record=FeedingRecordOut.model_validate(new_record))
