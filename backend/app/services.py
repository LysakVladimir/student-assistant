from datetime import date, datetime, timedelta
import httpx
from sqlalchemy.orm import Session
from .models import Lesson, BagRule, User

WEEKDAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
TYPE_RU = {"lecture":"лекция", "seminar":"семинар", "lab":"лабораторная", "physical":"физкультура", "exam":"экзамен", "other":"занятие"}

def lessons_for_date(db: Session, user: User, day: date) -> list[Lesson]:
    rows = db.query(Lesson).filter_by(user_id=user.id, weekday=day.weekday(), active=True).order_by(Lesson.start_time).all()
    # parity is reserved for future support; "both" works in MVP.
    return [x for x in rows if x.week_parity == "both" or x.week_parity in ("odd", "even")]

def find_windows(lessons: list[Lesson], threshold: int = 40) -> list[dict]:
    windows = []
    for first, second in zip(lessons, lessons[1:]):
        start = datetime.strptime(first.end_time, "%H:%M")
        end = datetime.strptime(second.start_time, "%H:%M")
        minutes = int((end-start).total_seconds() // 60)
        if minutes >= threshold:
            windows.append({"from": first.end_time, "to": second.start_time, "minutes": minutes})
    return windows

def bag_items(db: Session, user: User, lessons: list[Lesson]) -> list[str]:
    items = set()
    rules = db.query(BagRule).filter_by(user_id=user.id, enabled=True).all()
    for rule in rules:
        matched = rule.match_type == "always"
        for lesson in lessons:
            if rule.match_type == "type" and lesson.lesson_type == rule.match_value:
                matched = True
            elif rule.match_type == "keyword" and rule.match_value.lower() in lesson.subject.lower():
                matched = True
        if matched:
            items.update(x.strip() for x in rule.items.split(",") if x.strip())
    # Default contextual rules
    for lesson in lessons:
        if lesson.lesson_type == "physical":
            items.update(["спортивная форма", "спортивная обувь"])
        if lesson.lesson_type == "lab":
            items.update(["методичка", "тетрадь"])
        if lesson.lesson_type == "exam":
            items.update(["студенческий билет", "ручки"])
    return sorted(items)

async def get_weather(user: User, at: datetime | None = None) -> dict:
    # MVP: only works when a home address has been geocoded in a future iteration.
    # Open-Meteo geocoding by free text avoids requiring an API key.
    query = user.home_address.strip()
    if not query:
        return {"available": False, "message": "Укажите город или адрес в настройках, чтобы получать погоду."}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            geo = await client.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": query, "count": 1, "language": "ru", "format": "json"})
            geo.raise_for_status()
            results = geo.json().get("results", [])
            if not results:
                return {"available": False, "message": "Не удалось определить координаты адреса."}
            place = results[0]
            forecast = await client.get("https://api.open-meteo.com/v1/forecast", params={"latitude": place["latitude"], "longitude": place["longitude"], "hourly": "temperature_2m,precipitation,wind_speed_10m", "forecast_days": 2, "timezone": user.timezone})
            forecast.raise_for_status()
            data = forecast.json().get("hourly", {})
            times = data.get("time", [])
            target = (at or datetime.now()).strftime("%Y-%m-%dT%H:00")
            idx = min(range(len(times)), key=lambda i: abs((datetime.fromisoformat(times[i])-datetime.fromisoformat(target)).total_seconds())) if times else 0
            return {"available": bool(times), "place": place.get("name"), "time": times[idx] if times else None,
                    "temperature": data.get("temperature_2m", [None])[idx] if times else None,
                    "precipitation": data.get("precipitation", [None])[idx] if times else None,
                    "wind": data.get("wind_speed_10m", [None])[idx] if times else None}
    except Exception:
        return {"available": False, "message": "Сервис погоды временно недоступен."}

def build_plan(db: Session, user: User, day: date) -> dict:
    lessons = lessons_for_date(db, user, day)
    windows = find_windows(lessons)
    bag = bag_items(db, user, lessons)
    first = lessons[0] if lessons else None
    departure = None
    if first:
        start = datetime.combine(day, datetime.strptime(first.start_time, "%H:%M").time())
        departure = (start - timedelta(minutes=user.travel_minutes + user.prep_minutes + user.buffer_minutes)).strftime("%H:%M")
    return {
        "date": day.isoformat(), "weekday": WEEKDAYS_RU[day.weekday()],
        "lessons": [{"id": l.id, "subject": l.subject, "type": l.lesson_type, "type_label": TYPE_RU.get(l.lesson_type, "занятие"),
                     "start": l.start_time, "end": l.end_time, "room": l.room, "campus": l.campus, "notes": l.notes} for l in lessons],
        "windows": windows, "bag": bag, "first_lesson": first.start_time if first else None,
        "departure_time": departure, "travel_minutes": user.travel_minutes,
        "disclaimer": "Время выхода рассчитано по заданной длительности пути; пробки и фактический транспорт не подключены."
    }
