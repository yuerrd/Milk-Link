"""数据导出服务"""
import csv
import io
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RecordType
from app.services.reports import get_records_filtered


async def export_records_csv(
    db: AsyncSession,
    start_date: str | None = None,
    end_date: str | None = None,
    device_id: str | None = None,
    record_type: RecordType | None = None,
) -> tuple[str, str]:
    """
    导出记录为 CSV 格式
    
    Args:
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        device_id: 设备ID筛选
        record_type: 记录类型筛选
    
    Returns:
        (csv_content, filename) 元组
    """
    # 查询所有符合条件的记录（不分页）
    records, _ = await get_records_filtered(
        db,
        start_date=start_date,
        end_date=end_date,
        device_id=device_id,
        record_type=record_type,
        skip=0,
        limit=10000,  # 最多导出10000条
    )
    
    # 创建 CSV 内容
    output = io.StringIO()
    writer = csv.writer(output)
    
    # 写入表头（含中文）
    writer.writerow([
        "记录ID",
        "时间",
        "设备ID",
        "类型",
        "数量",
        "单位",
        "时段",
    ])
    
    # 写入数据行
    for r in records:
        record_type_cn = "喂奶" if r.record_type == RecordType.milk else "辅食"
        period_cn = "日间" if r.period.value == "day" else "夜间"
        
        # 格式化时间
        fed_at_str = r.fed_at.strftime("%Y-%m-%d %H:%M:%S")
        
        writer.writerow([
            r.id,
            fed_at_str,
            r.device_id,
            record_type_cn,
            r.amount_value,
            r.unit.value,
            period_cn,
        ])
    
    csv_content = output.getvalue()
    output.close()
    
    # 生成文件名
    today = datetime.now().strftime("%Y%m%d")
    if start_date and end_date:
        filename = f"milk-link-records-{start_date}-{end_date}.csv"
    elif start_date:
        filename = f"milk-link-records-from-{start_date}.csv"
    elif end_date:
        filename = f"milk-link-records-to-{end_date}.csv"
    else:
        filename = f"milk-link-records-{today}.csv"
    
    return csv_content, filename
