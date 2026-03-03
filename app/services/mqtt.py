"""MQTT 监听服务 — 处理设备通过 MQTT 上报的喂奶 / 辅食事件

主题结构（与固件 config.h 保持一致）：
  设备发布：{prefix}/{device_id}/feed    → 喂奶事件
            {prefix}/{device_id}/solid   → 辅食事件
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


def get_device_registry() -> dict[str, datetime]:
    """返回设备最后通信时间字典的快照（key=device_id, value=UTC datetime）。"""
    return dict(_device_last_seen)


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
    feed_topic = f"{prefix}/+/feed"
    solid_topic = f"{prefix}/+/solid"
    username = settings.mqtt_username or None
    password = settings.mqtt_password or None

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
                await client.subscribe(feed_topic, qos=1)
                await client.subscribe(solid_topic, qos=1)
                logger.info("[MQTT] Subscribed to %s and %s", feed_topic, solid_topic)

                async for message in client.messages:
                    topic_str = str(message.topic)
                    parts = topic_str.split("/")
                    # Expected: <prefix>/<device_id>/<action>
                    if len(parts) < 3:
                        continue

                    try:
                        payload = json.loads(message.payload)
                    except (json.JSONDecodeError, ValueError):
                        logger.warning("[MQTT] Invalid JSON from topic %s", topic_str)
                        continue

                    device_id = payload.get("device_id") or parts[-2]
                    action = parts[-1]
                    secret = payload.get("secret", "")
                    if secret != settings.device_secret:
                        logger.warning("[MQTT] Auth failed for device %s", device_id)
                        resp_topic = f"{prefix}/{device_id}/{action}/response"
                        await client.publish(
                            resp_topic, json.dumps({"status": 403}), qos=1
                        )
                        continue

                    logger.info("[MQTT] %s from %s", action, device_id)
                    # Store as naive UTC for consistent comparison with DB timestamps
                    _device_last_seen[device_id] = datetime.now(timezone.utc).replace(tzinfo=None)

                    if action == "feed":
                        task = asyncio.create_task(_handle_feed(device_id, client))
                        task.add_done_callback(_log_task_exception)
                    elif action == "solid":
                        task = asyncio.create_task(_handle_solid(device_id, client))
                        task.add_done_callback(_log_task_exception)

        except aiomqtt.MqttError as exc:
            logger.error("[MQTT] Connection error: %s — retrying in 5s", exc)
            await asyncio.sleep(5)
