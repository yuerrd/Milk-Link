"""add_unit_and_amount_value_fields

Revision ID: 360b08025977
Revises: b3f1a8e2c047
Create Date: 2026-03-05 22:24:30.471902

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '360b08025977'
down_revision: Union[str, Sequence[str], None] = 'b3f1a8e2c047'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 先检查并删除可能存在的列（如果之前迁移失败）
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = [col['name'] for col in inspector.get_columns('feeding_records')]
    
    # 1. 创建 Unit Enum 类型
    unit_enum = sa.Enum("ml", "g", name="unit")
    
    # 检查 unit type 是否已存在，避免重复创建
    try:
        unit_enum.create(op.get_bind(), checkfirst=True)
    except Exception:
        pass  # 类型已存在

    # 2. 添加 amount_value 列（如果不存在）
    if 'amount_value' not in existing_columns:
        op.add_column(
            "feeding_records",
            sa.Column("amount_value", sa.Integer(), nullable=True),
        )

    # 3. 添加 unit 列（如果不存在）
    if 'unit' not in existing_columns:
        op.add_column(
            "feeding_records",
            sa.Column("unit", unit_enum, nullable=True),
        )

    # 4. 数据迁移：复制 amount_ml 到 amount_value
    op.execute("UPDATE feeding_records SET amount_value = amount_ml WHERE amount_value IS NULL")

    # 5. 数据迁移：设置 unit
    #    检查 record_type 列是否存在
    if 'record_type' in existing_columns:
        # milk 类型 → 'ml', solid 类型 → 'g'（辅食改用克）
        op.execute("UPDATE feeding_records SET unit = 'ml' WHERE record_type = 'milk' AND unit IS NULL")
        op.execute("UPDATE feeding_records SET unit = 'g' WHERE record_type = 'solid' AND unit IS NULL")
    else:
        # 如果没有 record_type 列，默认全部设为 'ml'（向后兼容）
        op.execute("UPDATE feeding_records SET unit = 'ml' WHERE unit IS NULL")

    # 6. 设置 NOT NULL 约束（数据填充完毕后）- MySQL 需要指定类型
    op.alter_column(
        "feeding_records",
        "amount_value",
        existing_type=sa.Integer(),
        nullable=False
    )
    op.alter_column(
        "feeding_records",
        "unit",
        existing_type=unit_enum,
        nullable=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 删除新增的列
    op.drop_column("feeding_records", "unit")
    op.drop_column("feeding_records", "amount_value")
    # 删除 Enum 类型
    op.execute("DROP TYPE IF EXISTS unit")
