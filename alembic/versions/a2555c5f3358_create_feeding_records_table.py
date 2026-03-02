"""create feeding_records table

Revision ID: a2555c5f3358
Revises: 
Create Date: 2026-03-02 19:17:07.094378

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2555c5f3358'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feeding_records",
        sa.Column("id",        sa.Integer(),                                     nullable=False, autoincrement=True),
        sa.Column("device_id", sa.String(length=64),                             nullable=False),
        sa.Column("amount_ml", sa.Integer(),                                     nullable=False),
        sa.Column("period",    sa.Enum("day", "night", name="period"),           nullable=False),
        sa.Column("fed_at",    sa.DateTime(), server_default=sa.text("NOW()"),   nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feeding_records_device_id", "feeding_records", ["device_id"])
    op.create_index("ix_feeding_records_fed_at",    "feeding_records", ["fed_at"])


def downgrade() -> None:
    op.drop_index("ix_feeding_records_fed_at",    table_name="feeding_records")
    op.drop_index("ix_feeding_records_device_id", table_name="feeding_records")
    op.drop_table("feeding_records")
    op.execute("DROP TYPE IF EXISTS period")
