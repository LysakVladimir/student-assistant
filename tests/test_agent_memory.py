import asyncio
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db import Base
from backend.app.models import AnalysisQueue, ChatAccess, ChatMessage, MemoryFact, MonitorRule, TelegramChat, User
from backend.app import agent, memory


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db):
    alice = User(telegram_id=1, name="Alice")
    bob = User(telegram_id=2, name="Bob")
    chat = TelegramChat(telegram_chat_id=-100123, title="Учебная группа", analysis_enabled=True)
    private = TelegramChat(telegram_chat_id=-100999, title="Чужая группа", analysis_enabled=True)
    db.add_all([alice, bob, chat, private]); db.flush()
    db.add(ChatAccess(user_id=alice.id, chat_id=chat.id, role="member"))
    db.add(ChatAccess(user_id=bob.id, chat_id=private.id, role="member")); db.commit()
    return alice, bob, chat, private


def test_ingest_is_idempotent_and_extracts_task(monkeypatch):
    db = session(); alice, _, chat, _ = seed(db)
    monkeypatch.setattr(memory.ai_runtime, "embed_many", lambda db, texts: asyncio.sleep(0, result=[]))
    payload = {"chat_id": chat.telegram_chat_id, "message_id": 10, "author_id": 42, "author_name": "Иван",
               "sent_at": datetime.utcnow().isoformat(), "content": "Нужно сдать отчёт до пятницы", "content_type": "text"}
    first = asyncio.run(memory.ingest_message(db, payload))
    second = asyncio.run(memory.ingest_message(db, {**payload, "content": "Нужно сдать исправленный отчёт до пятницы"}))
    assert first["stored"] and second["stored"]
    assert db.query(ChatMessage).count() == 1
    assert db.query(AnalysisQueue).count() == 1
    assert db.query(ChatMessage).one().content.startswith("Нужно сдать исправленный")
    assert asyncio.run(memory.search_messages(db, alice, "сдать отчёт"))[0]["message_id"] == 10


def test_search_never_leaks_other_chat(monkeypatch):
    db = session(); alice, _, chat, private = seed(db)
    monkeypatch.setattr(memory.ai_runtime, "embed_many", lambda db, texts: asyncio.sleep(0, result=[]))
    db.add_all([
        ChatMessage(chat_id=chat.id, telegram_message_id=1, sent_at=datetime.utcnow(), content="Экзамен в понедельник"),
        ChatMessage(chat_id=private.id, telegram_message_id=2, sent_at=datetime.utcnow(), content="Секретный экзамен во вторник"),
    ]); db.commit()
    results = asyncio.run(memory.search_messages(db, alice, "экзамен"))
    assert {x["chat_id"] for x in results} == {chat.id}


def test_monitor_requires_access_and_has_cooldown(monkeypatch):
    db = session(); alice, _, chat, _ = seed(db)
    rule = MonitorRule(user_id=alice.id, chat_id=chat.id, query="перенос экзамена", cooldown_minutes=60)
    row = ChatMessage(chat_id=chat.id, telegram_message_id=3, sent_at=datetime.utcnow(), content="Объявили перенос экзамена")
    db.add_all([rule, row]); db.commit()
    assert len(memory.match_monitors(db, row, row.content)) == 1
    assert memory.match_monitors(db, row, row.content) == []


def test_batch_analysis_uses_one_call_for_multiple_messages(monkeypatch):
    db = session(); _, _, chat, _ = seed(db)
    async def fake_json(db, **kwargs):
        rows = db.query(ChatMessage).order_by(ChatMessage.id).all()
        return {"facts": [{"message_id": r.id, "kind": "task", "statement": r.content, "status": "open", "confidence": .9} for r in rows]}, {"model": "deepseek/deepseek-v4-flash"}
    monkeypatch.setattr(memory.ai_runtime, "generate_json", fake_json)
    monkeypatch.setattr(memory.ai_runtime, "embed_many", lambda db, texts: asyncio.sleep(0, result=[[.1, .2] for _ in texts]))
    for number, text in enumerate(("Подготовить доклад", "Сдать отчёт"), 1):
        asyncio.run(memory.ingest_message(db, {"chat_id": chat.telegram_chat_id, "message_id": number, "author_id": 7,
            "author_name": "Иван", "sent_at": datetime.utcnow().isoformat(), "content": text, "content_type": "text"}))
    result = asyncio.run(memory.process_analysis_queue(db))
    assert result["processed"] == 2
    assert db.query(AnalysisQueue).count() == 0
    assert all(x.processed for x in db.query(ChatMessage).all())


def test_real_failure_queries_are_routed_without_forced_tools():
    assert agent.classify_intent("Что такое рекурсия?") == "conversation"
    assert agent.classify_intent("Сравни символный ИИ и машинное обучение") == "conversation"
    assert agent.classify_intent("спасибо") == "conversation"
    assert agent.classify_intent("Какие завтра пары?") == "plan"
    assert agent.classify_intent("Что будет во вторник и среду?", has_chat_access=True) == "memory"
    assert agent.classify_intent("Преподавателя зовут Алексей Евгеньевич", has_chat_access=True, scoped_to_chat=True) == "memory"
    assert agent.classify_intent("Что такое рекурсия?", has_chat_access=True, scoped_to_chat=True) == "conversation"


def test_general_conversation_has_history_and_no_tools(monkeypatch):
    db = session(); alice, _, _, _ = seed(db)
    calls = []
    async def fake_chat(db, **kwargs):
        calls.append(kwargs)
        return {"role": "assistant", "content": "Простой ответ"}, {"model": "deepseek/deepseek-v4-flash"}
    monkeypatch.setattr(agent.ai_runtime, "chat", fake_chat)
    first = asyncio.run(agent.agent_reply(db, alice, "Что такое рекурсия?"))
    second = asyncio.run(agent.agent_reply(db, alice, "Объясни ещё проще"))
    assert first["answer"] == "Простой ответ" and second["answer"] == "Простой ответ"
    assert all("tools" not in call or call["tools"] is None for call in calls)
    assert any(item["content"] == "Что такое рекурсия?" for item in calls[1]["messages"])
    assert any(item["content"] == "Простой ответ" for item in calls[1]["messages"])


def test_group_memory_query_searches_raw_messages_before_batch_finishes(monkeypatch):
    db = session(); alice, _, chat, _ = seed(db)
    monkeypatch.setattr(memory.ai_runtime, "embed_many", lambda db, texts: asyncio.sleep(0, result=[]))
    asyncio.run(memory.ingest_message(db, {"chat_id": chat.telegram_chat_id, "message_id": 20, "author_id": 7,
        "author_name": "Иван", "sent_at": datetime.utcnow().isoformat(),
        "content": "Во вторник пары отменяют, а в среду работаем на Дворцовой площади", "content_type": "text"}))
    seen = {}
    async def fake_text(db, **kwargs):
        seen["prompt"] = kwargs["prompt"]
        return "Во вторник заявлена отмена, в среду — Дворцовая площадь [1].", {"model": "deepseek/deepseek-v4-flash"}
    monkeypatch.setattr(agent.ai_runtime, "generate_text", fake_text)
    result = asyncio.run(agent.agent_reply(db, alice, "Что будет во вторник и среду?"))
    assert "Дворцовой" in seen["prompt"]
    assert result["processing_pending"] == 1
    assert result["sources"][0]["message_id"] == 20


def test_rumour_is_kept_uncertain_even_if_model_overstates_it(monkeypatch):
    db = session(); _, _, chat, _ = seed(db)
    async def fake_json(db, **kwargs):
        row = db.query(ChatMessage).one()
        return {"facts": [{"message_id": row.id, "kind": "event", "statement": row.content,
                            "status": "confirmed", "confidence": .95}]}, {}
    monkeypatch.setattr(memory.ai_runtime, "generate_json", fake_json)
    monkeypatch.setattr(memory.ai_runtime, "embed_many", lambda db, texts: asyncio.sleep(0, result=[[] for _ in texts]))
    asyncio.run(memory.ingest_message(db, {"chat_id": chat.telegram_chat_id, "message_id": 30, "author_id": 7,
        "author_name": "Иван", "sent_at": datetime.utcnow().isoformat(),
        "content": "ГУАП сгорел, поэтому пары отменяют", "content_type": "text"}))
    asyncio.run(memory.process_analysis_queue(db))
    fact = db.query(MemoryFact).one()
    assert fact.status == "uncertain" and fact.confidence <= .5


def test_requested_unauthorized_chat_never_falls_back_to_other_access(monkeypatch):
    db = session(); alice, _, chat, private = seed(db)
    db.add(ChatMessage(chat_id=chat.id, telegram_message_id=99, sent_at=datetime.utcnow(), content="Секрет доступной группы")); db.commit()
    result = asyncio.run(agent.agent_reply(db, alice, "Что обсуждали в группе?", [private.id]))
    assert result["error"] == "chat_access_denied"
    assert result["sources"] == []
