from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.schemas import DailySummary, FeedingRecordOut, MonthlyReport, WeeklyReport

WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
_TZ = ZoneInfo(settings.timezone)


async def _post_markdown(content: str) -> None:
    if settings.debug_no_push:
        print(f"[DEBUG] WeChat push skipped:\n{content}")
        return
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            WEBHOOK_URL,
            params={"key": settings.wechat_webhook_key},
            json=payload,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("errcode") != 0:
            raise RuntimeError(f"企业微信推送失败: {result}")


# ── 日报（每次记录成功后触发）──────────────────────────────────────────────────

async def send_daily_report(all_records: list[FeedingRecordOut], today_str: str) -> None:
    """推送今日喂养记录（喂奶 + 辅食合并显示）"""
    if not all_records:
        return

    milk_records = [r for r in all_records if r.record_type == 'milk']
    total_ml = sum(r.amount_value for r in milk_records if r.unit.value == 'ml')
    milk_count = len(milk_records)

    row_lines = []
    for i, r in enumerate(all_records):
        time_str = r.fed_at.replace(tzinfo=_TZ).strftime('%H:%M')
        # 间隔基于相邻任意记录计算
        if i == 0:
            interval_str = "首次"
        else:
            delta = int((r.fed_at - all_records[i - 1].fed_at).total_seconds())
            h, m = divmod(delta // 60, 60)
            interval_str = f"间隔 {h}h{m:02d}m" if h > 0 else f"间隔 {m}m"

        if r.record_type == 'solid':
            # 辅食记录：如果有数值则显示克数，否则只显示"辅食"
            if r.amount_value > 0:
                row_lines.append(f"> {time_str}　🥣 **辅食 {r.amount_value}{r.unit.value}**　`{interval_str}`")
            else:
                row_lines.append(f"> {time_str}　🥣 **辅食**　`{interval_str}`")
        else:
            period_str = '夜晚' if r.period == 'night' else '白天'
            after_solid_tag = " `辅食后`" if (r.period == 'day' and r.amount_value == 120) else ""
            row_lines.append(
                f"> {time_str}　🍼 **{r.amount_value}{r.unit.value}**　({period_str}){after_solid_tag}　`{interval_str}`"
            )

    rows = "\n".join(row_lines)
    content = (
        f"## 🍼 今日喂养记录（{today_str}）\n"
        f"> 喂奶 **{milk_count}** 次　总量 **{total_ml}ml**\n\n"
        f"{rows}\n\n"
        f"> 💡 白天 160ml / 夜晚 90ml / 辅食后 120ml"
    )
    await _post_markdown(content)


# ── 周报（每周日 09:00 自动触发）─────────────────────────────────────────────

async def send_weekly_report(report: WeeklyReport) -> None:
    rows = "\n".join(
        f"> {d.date}　**{d.count}次**　{d.total_ml}ml"
        for d in report.days
    )
    if not rows:
        rows = "> 本周暂无记录"

    content = (
        f"## 📊 本周喂奶报表\n"
        f"> 统计周期：{report.week_start} ～ {report.week_end}\n\n"
        f"{rows}\n\n"
        f"> **合计：{report.total_count}次 / {report.total_ml}ml**\n"
        f"> 日均：{report.avg_count:.1f}次 / {report.avg_ml:.0f}ml"
    )
    await _post_markdown(content)


# ── 月报（每月 1 日 09:00 自动触发）──────────────────────────────────────────

async def send_monthly_report(report: MonthlyReport) -> None:
    rows = "\n".join(
        f"> {d.date}　**{d.count}次**　{d.total_ml}ml"
        for d in report.days
    )
    if not rows:
        rows = "> 本月暂无记录"

    content = (
        f"## 📈 {report.year}年{report.month}月喂奶月报\n\n"
        f"{rows}\n\n"
        f"> **合计：{report.total_count}次 / {report.total_ml}ml**\n"
        f"> 日均：{report.avg_count:.1f}次 / {report.avg_ml:.0f}ml"
    )
    await _post_markdown(content)
