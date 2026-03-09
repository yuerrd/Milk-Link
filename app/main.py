import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Union

# 配置日志：让 app.* 模块的 INFO 级别及以上日志输出到 stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import secrets

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal, engine, get_db, Base
from app.schemas import (
    AdminCreateRecord,
    AdminOverview,
    AdminRecordsResponse,
    AdminUpdateRecord,
    DeviceStatus,
    DailySummary,
    DuplicateResponse,
    FeedingRecordOut,
    FeedRequest,
    FeedResponse,
    MonthlyReport,
    SolidFoodRequest,
    SolidFoodResponse,
    TodayStats,
    WeeklyReport,
)
from app.models import RecordType
from app.services import feeding as feeding_svc
from app.services import mqtt as mqtt_svc
from app.services import reports as report_svc
from app.services import export as export_svc
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
_http_basic = HTTPBasic()


def require_admin(credentials: Annotated[HTTPBasicCredentials, Depends(_http_basic)]) -> None:
    """HTTP Basic Auth 验证管理后台访问权限。"""
    ok_user = secrets.compare_digest(
        credentials.username.encode(), settings.admin_username.encode()
    )
    ok_pass = secrets.compare_digest(
        credentials.password.encode(), settings.admin_password.encode()
    )
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Basic"},
        )


@app.get("/admin", include_in_schema=False)
async def admin_page(auth: Annotated[None, Depends(require_admin)]):
    """管理后台主页"""
    return FileResponse(os.path.join(_STATIC_DIR, "admin.html"))


@app.get(
    "/admin/api/overview",
    response_model=AdminOverview,
    summary="管理后台 — 综合概览",
    include_in_schema=False,
)
async def admin_overview(db: SessionDep, auth: Annotated[None, Depends(require_admin)]):
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
    online_map    = mqtt_svc.get_device_online()   # LWT 驱动的精确在线状态
    # 合并：DB 中出现的 + MQTT 中出现的 + 在线状态中出现的
    all_device_ids = sorted(
        set(device_ids_db) | set(mqtt_registry.keys()) | set(online_map.keys())
    )

    devices: list[DeviceStatus] = []
    for dev_id in all_device_ids:
        last_seen = mqtt_registry.get(dev_id)
        # 优先使用 LWT 状态；若设备从未发过 status 消息则降级到时间窗口（兼容旧固件）
        if dev_id in online_map:
            online = online_map[dev_id]
        else:
            from datetime import timedelta
            online = last_seen is not None and (
                datetime.now(timezone.utc).replace(tzinfo=None) - last_seen
            ) < timedelta(minutes=5)

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
    auth: Annotated[None, Depends(require_admin)],
    days: int = Query(default=7, ge=1, le=90),
):
    return await report_svc.get_daily_stats(db, days=days)


# ── 管理后台 查询 API ──────────────────────────────────────────────────────────

@app.get(
    "/admin/api/records",
    response_model=AdminRecordsResponse,
    summary="管理后台 — 查询记录（支持筛选和分页）",
    include_in_schema=False,
)
async def admin_list_records(
    db: SessionDep,
    auth: Annotated[None, Depends(require_admin)],
    start_date: str = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(None, description="结束日期 YYYY-MM-DD"),
    device_id: str = Query(None, description="设备ID筛选"),
    record_type: RecordType = Query(None, description="记录类型筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
):
    """查询记录，支持日期范围、设备、类型筛选及分页"""
    skip = (page - 1) * page_size
    records, total = await report_svc.get_records_filtered(
        db,
        start_date=start_date,
        end_date=end_date,
        device_id=device_id,
        record_type=record_type,
        skip=skip,
        limit=page_size,
    )
    return AdminRecordsResponse(
        records=records,
        total=total,
        page=page,
        page_size=page_size,
    )


@app.get(
    "/admin/api/records/daily/{date}",
    response_model=list[FeedingRecordOut],
    summary="管理后台 — 查询指定日期的记录",
    include_in_schema=False,
)
async def admin_daily_records(
    date: str,
    db: SessionDep,
    auth: Annotated[None, Depends(require_admin)],
    record_type: RecordType = Query(None, description="记录类型筛选"),
):
    """查询指定日期的所有记录（YYYY-MM-DD）"""
    return await report_svc.get_records_by_date(db, date, record_type)


@app.get(
    "/admin/api/records/export",
    summary="管理后台 — 导出记录为 CSV",
    include_in_schema=False,
)
async def admin_export_records(
    db: SessionDep,
    auth: Annotated[None, Depends(require_admin)],
    start_date: str = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(None, description="结束日期 YYYY-MM-DD"),
    device_id: str = Query(None, description="设备ID筛选"),
    record_type: RecordType = Query(None, description="记录类型筛选"),
):
    """导出记录为 CSV 文件（支持筛选条件）"""
    from fastapi.responses import StreamingResponse
    
    csv_content, filename = await export_svc.export_records_csv(
        db,
        start_date=start_date,
        end_date=end_date,
        device_id=device_id,
        record_type=record_type,
    )
    
    # 添加 BOM 以支持 Excel 正确显示中文
    csv_bytes = "\ufeff" + csv_content
    
    return StreamingResponse(
        iter([csv_bytes.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


# ── 管理后台 CRUD ─────────────────────────────────────────────────────────────

@app.post(
    "/admin/api/records/create",
    response_model=FeedingRecordOut,
    status_code=status.HTTP_201_CREATED,
    summary="管理后台 — 手动添加喂养记录",
    include_in_schema=False,
)
async def admin_create_record(
    body: AdminCreateRecord,
    db: SessionDep,
    auth: Annotated[None, Depends(require_admin)],
):
    from app.models import FeedingRecord as FeedingRecordModel

    record = FeedingRecordModel(
        device_id=body.device_id,
        record_type=body.record_type,
        amount_value=body.amount_value,
        unit=body.unit,
        period=body.period,
        fed_at=body.fed_at,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    await db.commit()
    return FeedingRecordOut.model_validate(record)


@app.put(
    "/admin/api/records/{record_id}",
    response_model=FeedingRecordOut,
    summary="管理后台 — 修改喂养记录",
    include_in_schema=False,
)
async def admin_update_record(
    record_id: int,
    body: AdminUpdateRecord,
    db: SessionDep,
    auth: Annotated[None, Depends(require_admin)],
):
    from app.models import FeedingRecord as FeedingRecordModel
    from sqlalchemy import select

    result = await db.execute(
        select(FeedingRecordModel).where(FeedingRecordModel.id == record_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")

    if body.record_type is not None:
        record.record_type = body.record_type
    if body.amount_value is not None:
        record.amount_value = body.amount_value
    if body.unit is not None:
        record.unit = body.unit
    if body.period is not None:
        record.period = body.period
    if body.fed_at is not None:
        record.fed_at = body.fed_at

    await db.flush()
    await db.refresh(record)
    await db.commit()
    return FeedingRecordOut.model_validate(record)


@app.delete(
    "/admin/api/records/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="管理后台 — 删除喂养记录",
    include_in_schema=False,
)
async def admin_delete_record(
    record_id: int,
    db: SessionDep,
    auth: Annotated[None, Depends(require_admin)],
):
    from app.models import FeedingRecord as FeedingRecordModel
    from sqlalchemy import select

    result = await db.execute(
        select(FeedingRecordModel).where(FeedingRecordModel.id == record_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")

    await db.delete(record)
    await db.commit()
