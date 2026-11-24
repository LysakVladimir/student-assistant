from datetime import date, datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from .db import get_db
from .migrations import apply_migrations
from .models import (User, Lesson, BagRule, TelegramChat, ChatAccess, ChatAISetting, ChatMessage, MemoryFact,
                     MonitorRule, AIUserSetting, AIProviderState, AnalysisQueue, AttachmentPayload, LLMCallLog)
from .schemas import UserPatch, LessonIn, BagRuleIn, LessonParseIn, ChatSettingsIn, MonitorRuleIn, AgentChatIn, AISettingsIn
from .config import settings
from .security import current_user
from .services import build_plan, save_guap_schedule, current_week_parity, get_weather_forecast
from .agent import agent_reply
from .memory import accessible_chat_ids, ingest_message, process_analysis_queue, purge_expired, search_messages
from . import ai_runtime, provider_client

import logging

logger = logging.getLogger(__name__)

apply_migrations()
app = FastAPI(title="StudyPilot API", version="0.1.0", description="Backend универсального интеллектуального ассистента студента")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/me")
def get_me(user: User = Depends(current_user)):
    return {k: getattr(user, k) for k in ["telegram_id","name","timezone","home_address","campus_name","travel_minutes","prep_minutes","buffer_minutes","travel_mode"]}

@app.patch("/api/me")
def patch_me(payload: UserPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return {"ok": True}

@app.get("/api/lessons")
def get_lessons(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(Lesson).filter_by(user_id=user.id).order_by(Lesson.weekday, Lesson.start_time).all()
    return [{"id":x.id,"subject":x.subject,"type":x.lesson_type,"weekday":x.weekday,"start":x.start_time,"end":x.end_time,"room":x.room,"campus":x.campus,"week_parity":x.week_parity,"notes":x.notes} for x in rows]

@app.post("/api/lessons")
def add_lesson(payload: LessonIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if payload.start_time >= payload.end_time:
        raise HTTPException(400, "Время начала должно быть раньше времени окончания")
    row = Lesson(user_id=user.id, subject=payload.subject, lesson_type=payload.lesson_type, weekday=payload.weekday,
                 start_time=payload.start_time, end_time=payload.end_time, room=payload.room, campus=payload.campus,
                 week_parity=payload.week_parity, notes=payload.notes)
    db.add(row); db.commit(); db.refresh(row)
    return {"id":row.id,"ok":True}

@app.delete("/api/lessons/{lesson_id}")
def delete_lesson(lesson_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.query(Lesson).filter_by(id=lesson_id, user_id=user.id).first()
    if not row: raise HTTPException(404, "Занятие не найдено")
    db.delete(row); db.commit()
    return {"ok":True}


@app.get("/api/week-parity")
def week_parity(day: str = "today"):
    """Чётность недели (odd/even) для фильтрации занятий."""
    target = date.today() + (timedelta(days=1) if day == "tomorrow" else timedelta())
    return {"parity": current_week_parity(target)}


@app.post("/api/lessons/parse")
def parse_lessons(payload: LessonParseIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Спарсить официальное расписание ГУАП по номеру группы.

    Текущие занятия пользователя заменяются спарсенными (replace=True), но только если сайт
    вернул расписание: при ошибке сайта/неверной группе старые данные не трогаются.
    """
    logger.info("[parse_lessons] user_id=%s group=%s", user.id, payload.group_name)
    try:
        saved = save_guap_schedule(db, user, payload.group_name.strip(), replace=True)
        logger.info("[parse_lessons] saved %d lessons for group=%s", len(saved), payload.group_name)
        return {"ok": True, "group": payload.group_name, "count": len(saved), "lessons": saved}
    except Exception as e:
        logger.exception("Ошибка при парсинге расписания для пользователя %s, группа %s: %s",
                         user.id, payload.group_name, e)
        raise HTTPException(500, f"Ошибка при парсинге расписания: {e}")


@app.get("/api/bag-rules")
def get_bag_rules(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [{"id":x.id,"match_type":x.match_type,"match_value":x.match_value,"items":x.items,"enabled":x.enabled} for x in db.query(BagRule).filter_by(user_id=user.id).all()]

@app.post("/api/bag-rules")
def add_bag_rule(payload: BagRuleIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = BagRule(user_id=user.id, match_type=payload.match_type, match_value=payload.match_value, items=payload.items)
    db.add(row); db.commit(); db.refresh(row)
    return {"id":row.id,"ok":True}

@app.delete("/api/bag-rules/{rule_id}")
def delete_bag_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.query(BagRule).filter_by(id=rule_id, user_id=user.id).first()
    if not row: raise HTTPException(404, "Правило не найдено")
    db.delete(row); db.commit()
    return {"ok":True}

@app.get("/api/weather")
async def weather(user: User = Depends(current_user)):
    """Погода по городу из настроек пользователя (город вводится на русском)."""
    return await get_weather_forecast(user)

@app.get("/api/plan")
def plan(day: str = "today", db: Session = Depends(get_db), user: User = Depends(current_user)):
    target = date.today() + (timedelta(days=1) if day == "tomorrow" else timedelta())
    return build_plan(db, user, target)

@app.get("/api/windows")
def windows(day: str = "today", db: Session = Depends(get_db), user: User = Depends(current_user)):
    target = date.today() + (timedelta(days=1) if day == "tomorrow" else timedelta())
    return build_plan(db, user, target)["windows"]

@app.post("/api/agent/chat")
async def chat(payload: AgentChatIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return await agent_reply(db, user, payload.message.strip(), payload.chat_ids, payload.detail)

@app.get("/api/agent/chats")
def agent_chats(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(ChatAccess, TelegramChat).join(TelegramChat, ChatAccess.chat_id == TelegramChat.id).filter(ChatAccess.user_id == user.id).all()
    return [{"id": c.id, "telegram_chat_id": c.telegram_chat_id, "title": c.title, "analysis_enabled": c.analysis_enabled,
             "interactive_enabled": c.interactive_enabled, "bot_active": c.bot_active, "access_enabled": a.enabled,
             "role": a.role, "custom_rules": a.custom_rules, "digest_mode": a.digest_mode, "digest_hour": a.digest_hour,
             "external_ai_enabled": (lambda s: s is None or s.external_ai_enabled is not False)(db.query(ChatAISetting).filter_by(chat_id=c.id).first())} for a,c in rows]

def _access(db: Session, user: User, chat_id: int) -> ChatAccess:
    row = db.query(ChatAccess).filter_by(user_id=user.id, chat_id=chat_id, enabled=True).first()
    if not row: raise HTTPException(403, "Нет доступа к этому чату")
    return row

@app.patch("/api/agent/chats/{chat_id}")
def patch_agent_chat(chat_id: int, payload: ChatSettingsIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    access = _access(db, user, chat_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "external_ai_enabled":
            if access.role not in {"administrator", "creator"}: raise HTTPException(403, "Передачу данных внешнему AI меняет администратор")
            chat_setting = db.query(ChatAISetting).filter_by(chat_id=chat_id).first()
            if not chat_setting: chat_setting = ChatAISetting(chat_id=chat_id); db.add(chat_setting)
            chat_setting.external_ai_enabled = value
        else: setattr(access, key, value)
    db.commit()
    return {"ok": True}

@app.delete("/api/agent/chats/{chat_id}/data")
def delete_agent_chat_data(chat_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    access = _access(db, user, chat_id)
    if access.role not in {"administrator", "creator"}:
        raise HTTPException(403, "Удалить общую историю может только администратор группы")
    message_ids = [x[0] for x in db.query(ChatMessage.id).filter_by(chat_id=chat_id).all()]
    if message_ids:
        db.query(AttachmentPayload).filter(AttachmentPayload.message_id.in_(message_ids)).delete(synchronize_session=False)
        db.query(AnalysisQueue).filter(AnalysisQueue.message_id.in_(message_ids)).delete(synchronize_session=False)
        db.query(MemoryFact).filter(MemoryFact.source_message_id.in_(message_ids)).delete(synchronize_session=False)
    db.query(ChatMessage).filter_by(chat_id=chat_id).delete()
    db.commit()
    return {"ok": True, "deleted_messages": len(message_ids)}

@app.post("/api/agent/chats/{chat_id}/import")
async def import_chat_history(chat_id: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    access = _access(db, user, chat_id)
    if access.role not in {"administrator", "creator"}: raise HTTPException(403, "Импортировать историю может только администратор")
    chat = db.get(TelegramChat, chat_id)
    messages = payload.get("messages", [])
    if not isinstance(messages, list) or len(messages) > 10000: raise HTTPException(400, "Ожидается Telegram JSON export, не более 10000 сообщений за запрос")
    imported = 0
    for item in messages:
        if item.get("type") not in {None, "message"} or not item.get("id"): continue
        raw_text = item.get("text", "")
        if isinstance(raw_text, list): raw_text = "".join(x if isinstance(x, str) else str(x.get("text", "")) for x in raw_text)
        result = await ingest_message(db, {"chat_id": chat.telegram_chat_id, "message_id": int(item["id"]), "author_id": None,
            "author_name": str(item.get("from", "")), "sent_at": str(item.get("date", datetime.utcnow().isoformat())),
            "reply_to_message_id": item.get("reply_to_message_id"), "content": str(raw_text), "content_type": "import"})
        imported += int(result.get("stored", False))
    return {"ok": True, "imported": imported}

@app.get("/api/agent/search")
async def agent_search(q: str, chat_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not q.strip(): raise HTTPException(400, "Поисковый запрос пуст")
    return await search_messages(db, user, q, [chat_id] if chat_id else None)

@app.get("/api/agent/facts")
def agent_facts(kind: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ids = accessible_chat_ids(db, user)
    query = db.query(MemoryFact).filter(MemoryFact.chat_id.in_(ids))
    if kind: query = query.filter_by(kind=kind)
    return [{"id": x.id, "chat_id": x.chat_id, "kind": x.kind, "statement": x.statement, "status": x.status,
             "confidence": x.confidence, "assignee": x.assignee, "due_at": x.due_at} for x in query.order_by(MemoryFact.created_at.desc()).limit(200).all()]

@app.get("/api/agent/monitors")
def monitors(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [{"id": x.id, "chat_id": x.chat_id, "query": x.query, "priority": x.priority, "cooldown_minutes": x.cooldown_minutes,
             "enabled": x.enabled, "last_notified_at": x.last_notified_at} for x in db.query(MonitorRule).filter_by(user_id=user.id).all()]

@app.post("/api/agent/monitors")
def add_monitor(payload: MonitorRuleIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if payload.chat_id is not None: _access(db, user, payload.chat_id)
    row = MonitorRule(user_id=user.id, **payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "ok": True}

@app.delete("/api/agent/monitors/{rule_id}")
def delete_monitor(rule_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.query(MonitorRule).filter_by(id=rule_id, user_id=user.id).first()
    if not row: raise HTTPException(404, "Правило не найдено")
    db.delete(row); db.commit()
    return {"ok": True}

@app.get("/api/agent/ai-settings")
def get_ai_settings(db: Session = Depends(get_db), user: User = Depends(current_user)):
    pref = ai_runtime.user_settings(db, user.id); db.commit()
    state = db.query(AIProviderState).filter_by(provider=provider_client.provider_name()).first()
    pending = db.query(AnalysisQueue).count()
    last_errors = db.query(LLMCallLog).filter_by(status="error").order_by(LLMCallLog.created_at.desc()).limit(5).all()
    is_admin = bool(settings.ai_admin_telegram_id and user.telegram_id == settings.ai_admin_telegram_id)
    return {"mode": pref.mode, "ai_enabled": pref.ai_enabled, "provider": provider_client.provider_name(), "is_admin": is_admin,
            "configured": provider_client.configured(), "primary_model": ai_runtime.select_model("complex_rag", "quality", "complex"),
            "background_model": ai_runtime.select_model("background_analysis", "auto"), "embedding_model": settings.ai_embedding_model,
            "provider_suspended_until": state.suspended_until if state else None, "provider_error": state.reason if state else "",
            "usage": ai_runtime.usage_stats(db, user.id), "application_usage": ai_runtime.usage_stats(db) if is_admin else None, "pending_messages": pending,
            "recent_errors": [{"operation": x.operation, "model": x.model, "code": x.error_code, "at": x.created_at} for x in last_errors] if is_admin else []}

@app.patch("/api/agent/ai-settings")
def patch_ai_settings(payload: AISettingsIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    pref = ai_runtime.user_settings(db, user.id)
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(pref, key, value)
    db.commit()
    return {"ok": True, "mode": pref.mode, "ai_enabled": pref.ai_enabled}

@app.post("/api/agent/ai-settings/reset-provider")
def reset_ai_provider(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not settings.ai_admin_telegram_id or user.telegram_id != settings.ai_admin_telegram_id:
        raise HTTPException(403, "Только администратор AI может сбросить блокировку провайдера")
    ai_runtime.reset_provider(db); db.commit()
    return {"ok": True}

@app.get("/api/agent/usage")
def agent_usage(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(LLMCallLog).filter_by(user_id=user.id).order_by(LLMCallLog.created_at.desc()).limit(100).all()
    return {"summary": ai_runtime.usage_stats(db, user.id), "calls": [{"at": x.created_at, "model": x.model, "operation": x.operation,
        "input_tokens": x.input_tokens, "output_tokens": x.output_tokens, "estimated_cost_rub": x.estimated_cost_rub,
        "duration_ms": x.duration_ms, "status": x.status, "error_code": x.error_code} for x in rows]}

def _verify_internal(token: str | None):
    expected = settings.internal_api_token or settings.app_secret
    if not expected or expected in {"change-me", "change-this-to-a-long-random-secret", "replace-with-a-long-random-value"} or token != expected:
        raise HTTPException(401, "Invalid internal token")

@app.post("/internal/telegram/message")
async def internal_message(payload: dict, x_internal_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    _verify_internal(x_internal_token)
    return await ingest_message(db, payload)

@app.post("/internal/agent/chat")
async def internal_agent_chat(payload: dict, x_internal_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    _verify_internal(x_internal_token)
    user = db.query(User).filter_by(telegram_id=int(payload.get("telegram_id", 0))).first()
    if not user: raise HTTPException(404, "Сначала выполните /start")
    message = str(payload.get("message", "")).strip()
    if not message: raise HTTPException(400, "Пустое сообщение")
    return await agent_reply(db, user, message, payload.get("chat_ids") or [], str(payload.get("detail", "normal")))

@app.post("/internal/agent/settings")
def internal_agent_settings(payload: dict, x_internal_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    _verify_internal(x_internal_token)
    user = db.query(User).filter_by(telegram_id=int(payload.get("telegram_id", 0))).first()
    if not user: raise HTTPException(404, "Сначала выполните /start")
    pref = ai_runtime.user_settings(db, user.id)
    mode = payload.get("mode")
    if mode is not None:
        if mode not in {"economy", "auto", "quality"}: raise HTTPException(400, "Режим: economy, auto или quality")
        pref.mode = mode
    if "ai_enabled" in payload: pref.ai_enabled = bool(payload["ai_enabled"])
    db.commit()
    return {"mode": pref.mode, "ai_enabled": pref.ai_enabled, "provider": provider_client.provider_name(),
            "primary_model": ai_runtime.select_model("complex_rag", pref.mode, "complex"), "background_model": ai_runtime.select_model("background_analysis", pref.mode)}

@app.post("/internal/analysis/run")
async def internal_analysis_run(x_internal_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    _verify_internal(x_internal_token)
    return await process_analysis_queue(db)

@app.post("/internal/maintenance")
def internal_maintenance(x_internal_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    _verify_internal(x_internal_token)
    return {"ok": True, "expired_messages_deleted": purge_expired(db, settings.message_retention_days)}
