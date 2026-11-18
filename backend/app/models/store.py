from sqlalchemy import CHAR, BigInteger, Identity, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(CHAR(3), server_default=text("'RON'"))
