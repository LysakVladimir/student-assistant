from datetime import datetime
from sqlalchemy import String, Integer, BigInteger, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="Студент")
    timezone: Mapped[str] = mapped_column(String(80), default="Europe/Moscow")
    home_address: Mapped[str] = mapped_column(String(255), default="")
    campus_name: Mapped[str] = mapped_column(String(255), default="Вуз")
    travel_minutes: Mapped[int] = mapped_column(Integer, default=35)
    prep_minutes: Mapped[int] = mapped_column(Integer, default=20)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=10)
    travel_mode: Mapped[str] = mapped_column(String(30), default="public_transport")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    lessons: Mapped[list["Lesson"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    bag_rules: Mapped[list["BagRule"]] = relationship(back_populates="user", cascade="all, delete-orphan")

class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(180))
    lesson_type: Mapped[str] = mapped_column(String(40), default="lecture")
    weekday: Mapped[int] = mapped_column(Integer)  # Monday=0
    start_time: Mapped[str] = mapped_column(String(5))  # HH:MM
    end_time: Mapped[str] = mapped_column(String(5))
    room: Mapped[str] = mapped_column(String(80), default="")
    campus: Mapped[str] = mapped_column(String(180), default="")
    week_parity: Mapped[str] = mapped_column(String(10), default="both")
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    user: Mapped["User"] = relationship(back_populates="lessons")

class BagRule(Base):
    __tablename__ = "bag_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    match_type: Mapped[str] = mapped_column(String(40), default="always") # always/type/keyword
    match_value: Mapped[str] = mapped_column(String(180), default="")
    items: Mapped[str] = mapped_column(Text)  # comma-separated MVP
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    user: Mapped["User"] = relationship(back_populates="bag_rules")
