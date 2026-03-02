"""add record_type to feeding_records

Revision ID: b3f1a8e2c047
Revises: a2555c5f3358
Create Date: 2026-03-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f1a8e2c047'
down_revision: Union[str, Sequence[str], None] = 'a2555c5f3358'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 先创建 Enum 类型（MySQL 直接内联，PostgreSQL 需显式创建）
    record_type_enum = sa.Enum("milk", "solid", name="recordtype")
    record_type_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "feeding_records",
        sa.Column(
            "record_type",
            record_type_enum,
            nullable=False,
            server_default="milk",
        ),
    )


def downgrade() -> None:
    op.drop_column("feeding_records", "record_type")
    op.execute("DROP TYPE IF EXISTS recordtype")
