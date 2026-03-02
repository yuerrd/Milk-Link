import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Period(str, enum.Enum):
    day = "day"
    night = "night"


class RecordType(str, enum.Enum):
    milk = "milk"
    solid = "solid"   # 辅食


class FeedingRecord(Base):
    __tablename__ = "feeding_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    record_type: Mapped[RecordType] = mapped_column(
        Enum(RecordType), nullable=False, default=RecordType.milk
    )
    amount_ml: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[Period] = mapped_column(Enum(Period), nullable=False)
    fed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True
    )
