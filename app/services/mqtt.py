"""MQTT 监听服务 — 处理设备通过 MQTT 上报的喂奶 / 辅食事件

主题结构（与固件 config.h 保持一致）：
  设备发布：{prefix}/{device_id}/feed    → 喂奶事件
            {prefix}/{device_id}/solid   → 辅食事件
            {prefix}/{device_id}/status  → 在线状态（LWT 离线 / 主动上线）
  服务端发布：{prefix}/{device_id}/feed/response
              {prefix}/{device_id}/solid/response
消息体（JSON）：{"device_id": "...", "secret": "..."}
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

import aiomqtt

from app.config import settings
from app.database import AsyncSessionLocal
from app.schemas import DuplicateResponse
from app.services import feeding as feeding_svc

logger = logging.getLogger(__name__)

# ── 设备在线注册表（内存中，进程重启后清空）──────────────────────────────────
# key: device_id, value: UTC datetime of last authenticated MQTT message
_device_last_seen: dict[str, datetime] = {}

# key: device_id, value: True=在线 / False=离线（由 LWT 和上线消息驱动）
_device_online: dict[str, bool] = {}

# key: device_id, value: asyncio.Lock（防止同一设备并发处理导致重复记录）
_device_locks: dict[str, asyncio.Lock] = {}


def get_device_registry() -> dict[str, datetime]:
    """返回设备最后通信时间字典的快照（key=device_id, value=UTC datetime）。"""
    return dict(_device_last_seen)


def get_device_online() -> dict[str, bool]:
    """返回设备在线状态快照（key=device_id, value=bool）。"""
    return dict(_device_online)


async def _handle_feed(device_id: str, client: aiomqtt.Client) -> None:
    async with AsyncSessionLocal() as db:
        try:
            result = await feeding_svc.record_feeding(db, device_id=device_id)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    if isinstance(result, DuplicateResponse):
        response = {"status": 409, "wait_seconds": result.wait_seconds}
    else:
        response = {
            "status": 201,
            "amount_ml": result.record.amount_ml,
            "period": result.record.period.value,
            "today_count": result.today_count,
            "today_total_ml": result.today_total_ml,
        }

    topic = f"{settings.mqtt_topic_prefix}/{device_id}/feed/response"
    await client.publish(topic, json.dumps(response), qos=1)


async def _handle_solid(device_id: str, client: aiomqtt.Client) -> None:
    async with AsyncSessionLocal() as db:
        try:
            result = await feeding_svc.record_solid_food(db, device_id=device_id)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    if isinstance(result, DuplicateResponse):
        response = {"status": 409, "wait_seconds": result.wait_seconds}
    else:
        response = {"status": 201}

    topic = f"{settings.mqtt_topic_prefix}/{device_id}/solid/response"
    await client.publish(topic, json.dumps(response), qos=1)


def _log_task_exception(task: asyncio.Task) -> None:
    """Callback attached to each handler task to log unhandled exceptions."""
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.error("[MQTT] Handler task raised an exception: %s", exc, exc_info=exc)


async def mqtt_listener() -> None:
    """连接 MQTT broker，持续监听设备消息，断线自动重连。"""
    prefix = settings.mqtt_topic_prefix
    feed_topic   = f"{prefix}/+/feed"
    solid_topic  = f"{prefix}/+/solid"
    status_topic = f"{prefix}/+/status"
    username = settings.mqtt_username or None
    password = settings.mqtt_password or None
    retry_delay = max(int(settings.mqtt_retry_initial_sec), 1)
    max_retry_delay = max(int(settings.mqtt_retry_max_sec), retry_delay)
    initial_retry_delay = retry_delay

    while True:
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_broker_host,
                port=settings.mqtt_broker_port,
                username=username,
                password=password,
            ) as client:
                logger.info(
                    "[MQTT] Connected to %s:%d",
                    settings.mqtt_broker_host,
                    settings.mqtt_broker_port,
                )
                retry_delay = initial_retry_delay
                await client.subscribe(feed_topic,   qos=1)
                await client.subscribe(solid_topic,  qos=1)
                await client.subscribe(status_topic, qos=1)
                logger.info("[MQTT] Subscribed to feed / solid / status topics")

                async for message in client.messages:
                    topic_str = str(message.topic)
                    parts = topic_str.split("/")
                    if len(parts) < 3:
                        continue

                    action    = parts[-1]   # feed / solid / status
                    device_id = parts[-2]

                    # ── 状态主题：无需认证，由 broker LWT 或设备直接发布 ──────
                    if action == "status":
                        try:
                            payload = json.loads(message.payload)
                            online = bool(payload.get("online", False))
                        except (json.JSONDecodeError, ValueError):
                            online = False
                        _device_online[device_id] = online
                        logger.info("[MQTT] Device %s is now %s",
                                    device_id, "ONLINE" if online else "OFFLINE")
                        continue

                    # ── 业务主题：需要认证 ────────────────────────────────────
                    try:
                        payload = json.loads(message.payload)
                    except (json.JSONDecodeError, ValueError):
                        logger.warning("[MQTT] Invalid JSON from topic %s", topic_str)
                        continue

                    secret = payload.get("secret", "")
                    if secret != settings.device_secret:
                        logger.warning("[MQTT] Auth failed for device %s", device_id)
                        resp_topic = f"{prefix}/{device_id}/{action}/response"
                        await client.publish(
                            resp_topic, json.dumps({"status": 403}), qos=1
                        )
                        continue

                    logger.info("[MQTT] %s from %s", action, device_id)
                    _device_last_seen[device_id] = datetime.now(timezone.utc).replace(tzinfo=None)

                    # 获取或创建设备锁（防止同设备并发导致重复记录）
                    if device_id not in _device_locks:
                        _device_locks[device_id] = asyncio.Lock()
                    
                    # 使用锁确保同一设备的消息顺序处理
                    async with _device_locks[device_id]:
                        if action == "feed":
                            await _handle_feed(device_id, client)
                        elif action == "solid":
                            await _handle_solid(device_id, client)

        except asyncio.CancelledError:
            logger.info("[MQTT] Listener cancelled, stopping")
            raise
        except aiomqtt.MqttError as exc:
            logger.error("[MQTT] Connection error: %s — retrying in %ss", exc, retry_delay)
        except Exception as exc:
            logger.exception("[MQTT] Unexpected error: %s — retrying in %ss", exc, retry_delay)

        await asyncio.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, max_retry_delay)
