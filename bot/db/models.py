from sqlalchemy import (
    BLOB,
    BigInteger,
    String,
    Text,
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
    accounts: Mapped[list["Account"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    folders: Mapped[list["AccountFolder"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class AccountFolder(Base):
    __tablename__ = "account_folders"

    name: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    user: Mapped["UserDB"] = relationship(back_populates="folders")
    accounts: Mapped[list["Account"]] = relationship(back_populates="folder")


class Account(Base):
    __tablename__ = "accounts"

    name: Mapped[str] = mapped_column(String(50), nullable=True)
    phone: Mapped[str] = mapped_column(String(50))
    api_id: Mapped[int] = mapped_column(BigInteger)
    api_hash: Mapped[str] = mapped_column(String(100))
    path_session: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("account_folders.id", ondelete="SET NULL"),
        nullable=True,
    )
    user: Mapped["UserDB"] = relationship(back_populates="accounts")
    folder: Mapped["AccountFolder | None"] = relationship(back_populates="accounts")

    is_connected: Mapped[bool] = mapped_column(default=False)
    is_started: Mapped[bool] = mapped_column(default=False)
    batch_size: Mapped[int] = mapped_column(nullable=False, default=5)
    usernames: Mapped[list["Username"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )
    texts: Mapped["AccountTexts | None"] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        uselist=False,
    )


class AccountTexts(Base):
    __tablename__ = "account_texts"

    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    account: Mapped["Account"] = relationship(back_populates="texts")

    greetings_morning: Mapped[list["GreetingMorning"]] = relationship(
        back_populates="account_texts",
        cascade="all, delete-orphan",
    )
    greetings_day: Mapped[list["GreetingDay"]] = relationship(
        back_populates="account_texts",
        cascade="all, delete-orphan",
    )
    greetings_evening: Mapped[list["GreetingEvening"]] = relationship(
        back_populates="account_texts",
        cascade="all, delete-orphan",
    )
    greetings_night: Mapped[list["GreetingNight"]] = relationship(
        back_populates="account_texts",
        cascade="all, delete-orphan",
    )
    greetings_anytime: Mapped[list["GreetingAnytime"]] = relationship(
        back_populates="account_texts",
        cascade="all, delete-orphan",
    )
    clarifying_texts: Mapped[list["ClarifyingText"]] = relationship(
        back_populates="account_texts",
        cascade="all, delete-orphan",
    )
    follow_up_texts: Mapped[list["FollowUpText"]] = relationship(
        back_populates="account_texts",
        cascade="all, delete-orphan",
    )
    lead_in_texts: Mapped[list["LeadInText"]] = relationship(
        back_populates="account_texts",
        cascade="all, delete-orphan",
    )
    closing_texts: Mapped[list["ClosingText"]] = relationship(
        back_populates="account_texts",
        cascade="all, delete-orphan",
    )


class AccountTextItemBase(Base):
    __abstract__ = True

    account_texts_id: Mapped[int] = mapped_column(
        ForeignKey("account_texts.id", ondelete="CASCADE"),
        nullable=False,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)


class GreetingMorning(AccountTextItemBase):
    __tablename__ = "account_greetings_morning"

    account_texts: Mapped["AccountTexts"] = relationship(
        back_populates="greetings_morning"
    )


class GreetingDay(AccountTextItemBase):
    __tablename__ = "account_greetings_day"

    account_texts: Mapped["AccountTexts"] = relationship(back_populates="greetings_day")


class GreetingEvening(AccountTextItemBase):
    __tablename__ = "account_greetings_evening"

    account_texts: Mapped["AccountTexts"] = relationship(
        back_populates="greetings_evening"
    )


class GreetingNight(AccountTextItemBase):
    __tablename__ = "account_greetings_night"

    account_texts: Mapped["AccountTexts"] = relationship(
        back_populates="greetings_night"
    )


class GreetingAnytime(AccountTextItemBase):
    __tablename__ = "account_greetings_anytime"

    account_texts: Mapped["AccountTexts"] = relationship(
        back_populates="greetings_anytime"
    )


class ClarifyingText(AccountTextItemBase):
    __tablename__ = "account_clarifying_texts"

    account_texts: Mapped["AccountTexts"] = relationship(
        back_populates="clarifying_texts"
    )


class FollowUpText(AccountTextItemBase):
    __tablename__ = "account_follow_up_texts"

    account_texts: Mapped["AccountTexts"] = relationship(
        back_populates="follow_up_texts"
    )


class LeadInText(AccountTextItemBase):
    __tablename__ = "account_lead_in_texts"

    account_texts: Mapped["AccountTexts"] = relationship(back_populates="lead_in_texts")


class ClosingText(AccountTextItemBase):
    __tablename__ = "account_closing_texts"

    account_texts: Mapped["AccountTexts"] = relationship(back_populates="closing_texts")


class Username(Base):
    __tablename__ = "usernames"

    account: Mapped["Account"] = relationship(back_populates="usernames")
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))

    username: Mapped[str] = mapped_column(String(100))
    item_name: Mapped[str] = mapped_column(String(100))
    sended: Mapped[bool] = mapped_column(default=False)


class Job(Base):
    __tablename__ = "jobs"

    account: Mapped["Account"] = relationship(back_populates="jobs")
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))

    name: Mapped[str] = mapped_column(String(50))
    mdata: Mapped[int] = mapped_column(BLOB, nullable=True)  # metadata
    answer: Mapped[int] = mapped_column(BLOB, nullable=True)
