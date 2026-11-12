from datetime import date, timedelta
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from .db import Base, engine, get_db
from .models import User, Lesson, BagRule
from .schemas import UserPatch, LessonIn, BagRuleIn, LessonParseIn
from .security import current_user
from .services import build_plan, save_guap_schedule, current_week_parity
from .agent import agent_reply

import logging

logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)
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

@app.get("/api/plan")
def plan(day: str = "today", db: Session = Depends(get_db), user: User = Depends(current_user)):
    target = date.today() + (timedelta(days=1) if day == "tomorrow" else timedelta())
    return build_plan(db, user, target)

@app.get("/api/windows")
def windows(day: str = "today", db: Session = Depends(get_db), user: User = Depends(current_user)):
    target = date.today() + (timedelta(days=1) if day == "tomorrow" else timedelta())
    return build_plan(db, user, target)["windows"]

@app.post("/api/agent/chat")
async def chat(payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    message = str(payload.get("message", "")).strip()
    if not message: raise HTTPException(400, "Сообщение не должно быть пустым")
    return await agent_reply(db, user, message)
