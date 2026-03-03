import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Union

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal, engine, get_db, Base
from app.schemas import (
    AdminOverview,
    DeviceStatus,
    DailySummary,
    DuplicateResponse,
    FeedRequest,
    FeedResponse,
    MonthlyReport,
    SolidFoodRequest,
    SolidFoodResponse,
    TodayStats,
    WeeklyReport,
)
from app.services import feeding as feeding_svc
from app.services import mqtt as mqtt_svc
from app.services import reports as report_svc
from app.services import wechat as wechat_svc

# ── 定时任务 ──────────────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler(timezone=settings.timezone)


async def _scheduled_weekly_report() -> None:
    async with AsyncSessionLocal() as db:
        report = await report_svc.get_week_records(db)
        await wechat_svc.send_weekly_report(report)


async def _scheduled_monthly_report() -> None:
    async with AsyncSessionLocal() as db:
        report = await report_svc.get_month_records(db)
        await wechat_svc.send_monthly_report(report)


# ── 应用生命周期 ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 建表（开发用；生产环境请用 alembic upgrade head）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 注册定时任务
    scheduler.add_job(
        _scheduled_weekly_report,
        CronTrigger(day_of_week="sun", hour=9, minute=0),
        id="weekly_report",
        replace_existing=True,
    )
    scheduler.add_job(
        _scheduled_monthly_report,
        CronTrigger(day=1, hour=9, minute=0),
        id="monthly_report",
        replace_existing=True,
    )
    scheduler.start()

    # 启动 MQTT 监听任务
    mqtt_task = asyncio.create_task(mqtt_svc.mqtt_listener())

    yield

    mqtt_task.cancel()
    try:
        await mqtt_task
    except asyncio.CancelledError:
        pass

    scheduler.shutdown(wait=False)
    await engine.dispose()


# ── FastAPI 实例 ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Milk-Link API",
    description="M5Stack DualKey 喂奶记录 → 企业微信推送",
    version="1.0.0",
    lifespan=lifespan,
)

SessionDep = Annotated[AsyncSession, Depends(get_db)]


# ── 路由 ──────────────────────────────────────────────────────────────────────

@app.post(
    "/feed",
    status_code=status.HTTP_201_CREATED,
    response_model=Union[FeedResponse, DuplicateResponse],
    summary="记录一次喂奶",
    responses={
        201: {"description": "成功记录，并推送当日明细到企业微信"},
        409: {"description": "5分钟内重复提交，已忽略"},
        403: {"description": "设备密钥错误"},
    },
)
async def feed(req: FeedRequest, db: SessionDep):
    if req.secret != settings.device_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="设备密钥错误")

    result = await feeding_svc.record_feeding(db, device_id=req.device_id)

    if isinstance(result, DuplicateResponse):
        # 返回 409 但仍包含 body
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=result.model_dump(mode="json"),
        )
    return result


@app.post(
    "/solid",
    status_code=status.HTTP_201_CREATED,
    response_model=SolidFoodResponse,
    summary="记录一次辅食",
    responses={
        201: {"description": "成功记录辅食，下次喂奶将为 120ml"},
        409: {"description": "2分钟内重复提交，已忽略"},
        403: {"description": "设备密钥错误"},
    },
)
async def solid(req: SolidFoodRequest, db: SessionDep):
    if req.secret != settings.device_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="设备密钥错误")

    result = await feeding_svc.record_solid_food(db, device_id=req.device_id)

    if isinstance(result, DuplicateResponse):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=result.model_dump(mode="json"),
        )
    return result


@app.get(
    "/stats/today",
    response_model=TodayStats,
    summary="查询今日喂奶统计",
)
async def stats_today(db: SessionDep):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    records = await report_svc.get_today_records(db)
    today_str = datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d")
    return TodayStats(
        date=today_str,
        count=len(records),
        total_ml=sum(r.amount_ml for r in records),
        records=records,
    )


@app.post(
    "/report/weekly",
    response_model=WeeklyReport,
    summary="手动触发周报推送（调试用）",
)
async def trigger_weekly(db: SessionDep):
    report = await report_svc.get_week_records(db)
    await wechat_svc.send_weekly_report(report)
    return report


@app.post(
    "/report/monthly",
    response_model=MonthlyReport,
    summary="手动触发月报推送（调试用）",
)
async def trigger_monthly(db: SessionDep):
    report = await report_svc.get_month_records(db)
    await wechat_svc.send_monthly_report(report)
    return report


@app.get("/health", summary="健康检查")
async def health():
    return {"status": "ok"}


# ── 管理后台 ───────────────────────────────────────────────────────────────────

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    """管理后台主页"""
    return FileResponse(os.path.join(_STATIC_DIR, "admin.html"))


@app.get(
    "/admin/api/overview",
    response_model=AdminOverview,
    summary="管理后台 — 综合概览",
    include_in_schema=False,
)
async def admin_overview(db: SessionDep):
    from zoneinfo import ZoneInfo

    now_local = datetime.now(ZoneInfo(settings.timezone))
    today_str = now_local.strftime("%Y-%m-%d")

    # 今日喂奶汇总
    today_records = await report_svc.get_today_records(db)
    today_count = len(today_records)
    today_total_ml = sum(r.amount_ml for r in today_records)

    # 构建设备状态列表
    device_ids_db = await report_svc.get_all_device_ids(db)
    mqtt_registry = mqtt_svc.get_device_registry()
    # 合并：DB 中出现的 + MQTT 中出现的
    all_device_ids = sorted(set(device_ids_db) | set(mqtt_registry.keys()))

    # Both now_utc and _device_last_seen values are naive UTC datetimes
    # (DB stores naive UTC, mqtt.py stores datetime.now(timezone.utc).replace(tzinfo=None))
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    online_threshold = timedelta(minutes=5)

    devices: list[DeviceStatus] = []
    for dev_id in all_device_ids:
        last_seen = mqtt_registry.get(dev_id)
        online = last_seen is not None and (now_utc - last_seen) < online_threshold

        last_rec = await report_svc.get_device_last_record(db, dev_id)
        last_record_at = last_rec.fed_at if last_rec else None
        last_record_type = last_rec.record_type if last_rec else None

        dev_count, dev_total = await report_svc.get_today_device_stats(db, dev_id)
        devices.append(DeviceStatus(
            device_id=dev_id,
            online=online,
            last_seen=last_seen,
            last_record_at=last_record_at,
            last_record_type=last_record_type,
            today_count=dev_count,
            today_total_ml=dev_total,
        ))

    recent = await report_svc.get_recent_records(db, limit=50)

    return AdminOverview(
        date=today_str,
        today_count=today_count,
        today_total_ml=today_total_ml,
        devices=devices,
        recent_records=recent,
    )


@app.get(
    "/admin/api/stats/daily",
    response_model=list[DailySummary],
    summary="管理后台 — 近 N 日每日统计",
    include_in_schema=False,
)
async def admin_daily_stats(
    db: SessionDep,
    days: int = Query(default=7, ge=1, le=90),
):
    return await report_svc.get_daily_stats(db, days=days)


# 挂载静态文件（CSS / JS 等，如有）
app.mount("/admin/static", StaticFiles(directory=_STATIC_DIR), name="admin-static")
