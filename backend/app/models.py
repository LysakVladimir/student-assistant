from datetime import datetime
from sqlalchemy import String, Integer, BigInteger, Boolean, DateTime, ForeignKey, Text, Float, UniqueConstraint
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

class TelegramChat(Base):
    __tablename__ = "telegram_chats"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    chat_type: Mapped[str] = mapped_column(String(30), default="group")
    bot_active: Mapped[bool] = mapped_column(Boolean, default=True)
    analysis_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    interactive_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    notice_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatAccess(Base):
    __tablename__ = "chat_access"
    __table_args__ = (UniqueConstraint("user_id", "chat_id", name="uq_chat_access_user_chat"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("telegram_chats.id"), index=True)
    role: Mapped[str] = mapped_column(String(30), default="member")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    custom_rules: Mapped[str] = mapped_column(Text, default="")
    digest_mode: Mapped[str] = mapped_column(String(30), default="off")
    digest_hour: Mapped[int] = mapped_column(Integer, default=20)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (UniqueConstraint("chat_id", "telegram_message_id", name="uq_chat_message"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("telegram_chats.id"), index=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger)
    author_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    author_name: Mapped[str] = mapped_column(String(255), default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reply_to_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    content_type: Mapped[str] = mapped_column(String(30), default="text")
    attachment_file_id: Mapped[str] = mapped_column(String(255), default="")
    attachment_name: Mapped[str] = mapped_column(String(255), default="")
    extracted_content: Mapped[str] = mapped_column(Text, default="")
    embedding_json: Mapped[str] = mapped_column(Text, default="")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class MemoryFact(Base):
    __tablename__ = "memory_facts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("telegram_chats.id"), index=True)
    source_message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="fact", index=True)
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="proposed")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    assignee: Mapped[str] = mapped_column(String(255), default="")
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("memory_facts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class MonitorRule(Base):
    __tablename__ = "monitor_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    chat_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_chats.id"), nullable=True, index=True)
    query: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_message_id: Mapped[int | None] = mapped_column(ForeignKey("chat_messages.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class AgentConversation(Base):
    __tablename__ = "agent_conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    selected_chat_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_chats.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class LLMUsage(Base):
    __tablename__ = "llm_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(String(40))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class AgentNotification(Base):
    __tablename__ = "agent_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class AIUserSetting(Base):
    __tablename__ = "ai_user_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(20), default="auto")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    monthly_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatAISetting(Base):
    __tablename__ = "chat_ai_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("telegram_chats.id"), unique=True, index=True)
    external_ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AnalysisQueue(Base):
    __tablename__ = "analysis_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id"), unique=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class AttachmentPayload(Base):
    __tablename__ = "attachment_payloads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id"), unique=True, index=True)
    mime_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    base64_data: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class AIProviderState(Base):
    __tablename__ = "ai_provider_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    suspended_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str] = mapped_column(String(80), default="")
    last_error: Mapped[str] = mapped_column(String(500), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class LLMCallLog(Base):
    __tablename__ = "llm_call_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    model: Mapped[str] = mapped_column(String(160), index=True)
    operation: Mapped[str] = mapped_column(String(50), index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_rub: Mapped[float] = mapped_column(Float, default=0.0)
    provider_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="success", index=True)
    error_code: Mapped[str] = mapped_column(String(50), default="")
    error_message: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
