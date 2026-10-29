import json
import httpx
from datetime import date, timedelta
from sqlalchemy.orm import Session
from .config import settings
from .models import User
from .services import build_plan

TOOLS = [
    {"name":"get_plan","description":"Получить расписание, окна и рюкзак на сегодня или завтра","parameters":{"type":"OBJECT","properties":{"day":{"type":"STRING","enum":["today","tomorrow"]}},"required":["day"]}},
    {"name":"get_departure_advice","description":"Получить время выхода и расчёт плана на сегодня или завтра","parameters":{"type":"OBJECT","properties":{"day":{"type":"STRING","enum":["today","tomorrow"]}},"required":["day"]}}
]

async def agent_reply(db: Session, user: User, message: str) -> dict:
    msg = message.lower()
    if settings.gemini_api_key:
        try:
            return await _gemini_tool_call(db, user, message)
        except Exception:
            pass
    day = date.today() + (timedelta(days=1) if any(x in msg for x in ["завтра", "tomorrow"]) else timedelta())
    plan = build_plan(db, user, day)
    if any(x in msg for x in ["рюкзак", "взять", "вещи", "форма", "методичк"]):
        answer = "На этот день стоит взять: " + (", ".join(plan["bag"]) if plan["bag"] else "список пока пуст — добавьте правила в Mini App.")
    elif any(x in msg for x in ["окно", "перерыв", "свобод"]):
        answer = "Свободные окна: " + ("; ".join(f'{w["from"]}–{w["to"]} ({w["minutes"]} мин.)' for w in plan["windows"]) if plan["windows"] else "не обнаружены.")
    elif any(x in msg for x in ["выйти", "маршрут", "опозд", "дорог"]):
        answer = f'Рекомендованное время выхода: {plan["departure_time"]}.' if plan["departure_time"] else "На выбранный день занятия не добавлены."
    else:
        answer = f'План на {plan["weekday"].lower()}: {len(plan["lessons"])} занятий. ' + (f'Первое начинается в {plan["first_lesson"]}, выйти ориентировочно в {plan["departure_time"]}.' if plan["first_lesson"] else "Занятий нет.")
    return {"answer": answer, "used_llm": False, "tools": ["get_plan"]}

async def _gemini_tool_call(db: Session, user: User, message: str) -> dict:
    # LLM selects a declared tool; tool results and calculations remain deterministic.
    schema = {"type":"OBJECT","properties":{"tool":{"type":"STRING","enum":["get_plan","get_departure_advice"]},"day":{"type":"STRING","enum":["today","tomorrow"]}},"required":["tool","day"]}
    prompt = ("Ты StudyPilot — помощник студента. Выбери инструмент и день по сообщению. "
              "Не выдумывай данные. Верни только поля, соответствующие JSON-схеме. Сообщение: " + message)
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
            params={"key": settings.gemini_api_key},
            json={"contents":[{"parts":[{"text":prompt}]}],
                  "generationConfig":{"responseMimeType":"application/json","responseSchema":schema}}
        )
        response.raise_for_status()
        raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        choice = json.loads(raw)
    day = date.today() + (timedelta(days=1) if choice["day"] == "tomorrow" else timedelta())
    plan = build_plan(db, user, day)
    if choice["tool"] == "get_departure_advice":
        answer = f'Для первой пары в {plan["first_lesson"]} расчётное время выхода — {plan["departure_time"]}.' if plan["first_lesson"] else "На этот день занятий нет."
    else:
        answer = f'План на {plan["weekday"].lower()}: {len(plan["lessons"])} занятий. Вещи: {", ".join(plan["bag"]) or "не указаны"}.'
    return {"answer": answer, "used_llm": True, "tools": [choice["tool"]]}
