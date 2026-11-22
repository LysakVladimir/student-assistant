import asyncio
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import agent, memory
from backend.app import migrations

# main.py applies production migrations at import time. Disable only that
# import-side effect; the endpoints below still run against a real SQLAlchemy DB.
migrations.apply_migrations = lambda: None
from backend.app import main
from backend.app.db import Base
from backend.app.models import ChatAccess, ChatMessage, TelegramChat, User


def test_internal_telegram_to_memory_query_pipeline(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    with TestingSession() as db:
        user = User(telegram_id=42, name="Иван")
        chat = TelegramChat(telegram_chat_id=-100123, title="Учебная группа", bot_active=True, analysis_enabled=True)
        db.add_all([user, chat]); db.flush()
        db.add(ChatAccess(user_id=user.id, chat_id=chat.id, role="member")); db.commit()
        chat_db_id = chat.id

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(main.settings, "internal_api_token", "test-secret")
    monkeypatch.setattr(memory.ai_runtime, "embed_many", lambda db, texts: asyncio.sleep(0, result=[]))
    async def fake_text(db, **kwargs):
        return "Собрание перенесли на четверг, 16:00, аудитория 410 [1].", {"model": "deepseek/deepseek-v4-flash"}
    monkeypatch.setattr(agent.ai_runtime, "generate_text", fake_text)
    main.app.dependency_overrides[main.get_db] = override_db
    try:
        with TestClient(main.app) as client:
            stored = client.post("/internal/telegram/message", headers={"X-Internal-Token": "test-secret"}, json={
                "chat_id": -100123, "message_id": 77, "author_id": 42, "author_name": "Иван",
                "sent_at": datetime.utcnow().isoformat(), "content": "Собрание переносится на четверг, 16:00, аудитория 410",
                "content_type": "text", "priority": 10,
            })
            assert stored.status_code == 200 and stored.json()["stored"] is True
            reply = client.post("/internal/agent/chat", headers={"X-Internal-Token": "test-secret"}, json={
                "telegram_id": 42, "message": "Когда и где состоится собрание? Как менялись договоренности?",
                "chat_ids": [chat_db_id],
            })
            assert reply.status_code == 200
            data = reply.json()
            assert "четверг" in data["answer"].lower()
            assert data["sources"][0]["message_id"] == 77
            assert data["processing_pending"] == 1
        with TestingSession() as db:
            assert db.query(ChatMessage).filter_by(telegram_message_id=77).one().processed is False
    finally:
        main.app.dependency_overrides.clear()
