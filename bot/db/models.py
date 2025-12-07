from sqlalchemy import (
    BigInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm.properties import ForeignKey

from .base import Base


class UserDB(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(100))
    username: Mapped[str] = mapped_column(String(100))

    is_admin: Mapped[bool] = mapped_column(nullable=False, default=False)


class Account(Base):
    __tablename__ = "accounts"

    name: Mapped[str] = mapped_column(String(50), nullable=True)
    phone: Mapped[str] = mapped_column(String(50))
    api_id: Mapped[int] = mapped_column(BigInteger)
    api_hash: Mapped[str] = mapped_column(String(100))
    path_session: Mapped[str] = mapped_column(String(100))

    is_connected: Mapped[bool] = mapped_column(default=False)
    is_started: Mapped[bool] = mapped_column(default=False)
    usernames: Mapped[list["Username"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )


class Username(Base):
    __tablename__ = "usernames"

    account: Mapped["Account"] = relationship(back_populates="usernames")
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))

    username: Mapped[str] = mapped_column(String(100))
    item_name: Mapped[str] = mapped_column(String(100))
    sended: Mapped[bool] = mapped_column(default=False)
