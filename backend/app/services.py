import logging
from datetime import date, datetime, timedelta
import httpx
from sqlalchemy.orm import Session
from .models import Lesson, BagRule, User
from .config import settings
import requests
from bs4 import BeautifulSoup
import json
import re
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

WEEKDAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
TYPE_RU = {"lecture":"лекция", "seminar":"семинар", "lab":"лабораторная", "physical":"физкультура", "exam":"экзамен", "other":"занятие"}

def current_week_parity(on: date | None = None, reference_date: date | None = None) -> str:
    """Чётность недели, в которую попадает дата `on` (по умолчанию сегодня): "odd" или "even".

    Точка отсчёта — любая дата внутри НЕЧЁТНОЙ недели. Порядок выбора:
    1) аргумент reference_date;
    2) переменная окружения ODD_WEEK_REFERENCE (YYYY-MM-DD) — рекомендуется задать,
       если расчёт расходится с сайтом ГУАП;
    3) 1 сентября ближайшего учебного года (первая неделя — нечётная).
    """
    on = on or date.today()
    if reference_date is None and settings.odd_week_reference:
        try:
            reference_date = date.fromisoformat(settings.odd_week_reference)
        except ValueError:
            logger.warning("ODD_WEEK_REFERENCE=%r не похоже на YYYY-MM-DD, игнорирую", settings.odd_week_reference)
    if reference_date is None:
        year = on.year if on >= date(on.year, 9, 1) else on.year - 1
        reference_date = date(year, 9, 1)
    ref_monday = reference_date - timedelta(days=reference_date.weekday())
    day_monday = on - timedelta(days=on.weekday())
    weeks_passed = (day_monday - ref_monday).days // 7
    return "odd" if weeks_passed % 2 == 0 else "even"


def lessons_for_date(db: Session, user: User, day: date) -> list[Lesson]:
    rows = db.query(Lesson).filter_by(user_id=user.id, weekday=day.weekday(), active=True).order_by(Lesson.start_time).all()
    # Чётность считаем для самой даты, а не для «сегодня»: в воскресенье «завтра» уже другая неделя.
    parity = current_week_parity(day)
    return [x for x in rows if x.week_parity == "both" or x.week_parity == parity]

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






#________________________________________________________
# Парсинг официального расписания ГУАП (https://guap.ru/rasp)

def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def get_group_id_by_name(group_name):
    """Ищет ID группы по названию, парся главную страницу расписания ГУАП.

    На сайте ГУАП группы задаются в выпадающем списке <select id="selGroup">
    с <option value="ID">Название</option>, а не ссылками ?gr=.
    """
    logger.info("[get_group_id_by_name] ищем ID для группы %s", group_name)
    url = "https://guap.ru/rasp"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.exception("[get_group_id_by_name] ошибка при запросе списка групп: %s", e)
        return None
    soup = BeautifulSoup(response.text, 'html.parser')
    select = soup.find('select', id='selGroup')
    if not select:
        logger.warning("[get_group_id_by_name] не найден список групп #selGroup на странице")
        return None
    options = select.find_all('option')
    logger.info("[get_group_id_by_name] найдено %d опций в списке групп", len(options))
    for opt in options:
        if clean_text(opt.text) == group_name:
            group_id = opt.get('value')
            if group_id:
                logger.info("[get_group_id_by_name] успех: группа %s имеет ID %s", group_name, group_id)
                return group_id
    logger.warning("[get_group_id_by_name] группа %s не найдена в выпадающем списке", group_name)
    return None

def get_guap_schedule_by_name(group_name):
    # 1. Сначала получаем ID (7103)
    group_id = get_group_id_by_name(group_name)
    if not group_id:
        return None
        
    # 2. Теперь запрашиваем расписание по ID
    url = f"https://guap.ru/rasp?gr={group_id}"
    print(f"Загружаем расписание для ID {group_id}...")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе: {e}")
        return None

    return parse_schedule_html(response.text, group_name)

def parse_schedule_html(html, group_name=""):
    """Разбирает HTML страницы https://guap.ru/rasp?gr=ID в {день: [занятия]}."""
    soup = BeautifulSoup(html, 'html.parser')
    container = soup.find('div', class_='container content mb-5')
    if not container:
        logger.warning("Контейнер расписания не найден в HTML для группы %s.", group_name)
        return None

    schedule = {}
    current_day = None
    
    for day_header in container.find_all('h4', class_='text-danger'):
        current_day = clean_text(day_header.text)
        schedule[current_day] = []
        
        sibling = day_header.next_sibling
        current_time = ""
        
        while sibling and sibling.name != 'h4':
            if sibling.name == 'div':
                classes = sibling.get('class', [])
                
                if 'mt-3' in classes and 'text-danger' in classes:
                    current_time = clean_text(sibling.text)
                
                elif 'mb-3' in classes and 'py-2' in classes and 'd-flex' in classes:
                    lesson_data = {
                        "time": current_time,
                        "week": "",
                        "week_class": "",
                        "type": "",
                        "subject": "",
                        "location": "",
                        "department": "",
                        "teacher": "",
                        "groups": []
                    }
                    
                    # Маркер недели: элемент с классом week1/week2 и подсказкой (title) «Чётная/Нечётная неделя».
                    # Пары без маркера идут на обеих неделях.
                    week_el = sibling.find(class_=re.compile(r'^week[12]$'))
                    if week_el:
                        lesson_data["week"] = week_el.get('title', '') or ''
                        lesson_data["week_class"] = next(
                            (c for c in week_el.get('class', []) if re.fullmatch(r'week[12]', c)), '')
                    
                    type_div = sibling.find('div', class_='fs-6 lh-sm opacity-50')
                    if type_div: lesson_data["type"] = clean_text(type_div.text)
                    
                    subject_div = sibling.find('div', class_='lead lh-sm')
                    if subject_div: lesson_data["subject"] = clean_text(subject_div.text)
                    
                    details_div = sibling.find('div', class_='opacity-75')
                    if details_div:
                        ad_link = details_div.find('a', href=re.compile(r'\?ad='))
                        if ad_link: lesson_data["location"] = clean_text(ad_link.text)
                        
                        ch_link = details_div.find('a', href=re.compile(r'\?ch='))
                        if ch_link: lesson_data["department"] = clean_text(ch_link.text)
                        
                        pr_link = details_div.find('a', href=re.compile(r'\?pr='))
                        if pr_link: lesson_data["teacher"] = clean_text(pr_link.text)
                        
                        gr_links = details_div.find_all('a', href=re.compile(r'\?gr='))
                        lesson_data["groups"] = [clean_text(a.text) for a in gr_links]
                    
                    schedule[current_day].append(lesson_data)
            
            sibling = sibling.next_sibling

    total_lessons = sum(len(v) for v in schedule.values())
    logger.info("[get_guap_schedule_by_name] распарсено %d занятий по %d дням для группы %s",
                total_lessons, len(schedule), group_name)
    return schedule

def get_guap_schedule_by_id(group_id):
    """Загружает расписание по ID группы (строка/число). Возвращает расписание или None."""
    return get_guap_schedule_by_name(str(group_id))


def parse_week_parity(week_title: str, week_class: str = "") -> str:
    """Переводит пометку недели с сайта ГУАП в week_parity: "odd" / "even" / "both".

    ВАЖНО: «нечётная» содержит в себе «чётная», поэтому сначала проверяем «нечет»,
    иначе все нечётные пары записываются как чётные.
    Приоритет: текст подсказки (title) -> CSS-класс week1/week2 -> "both" (каждую неделю).
    """
    text = clean_text(week_title).lower().replace("ё", "е")
    if "нечет" in text or "odd" in text:
        return "odd"
    if "чет" in text or "even" in text:
        return "even"
    if week_class == "week1":
        return "odd"
    if week_class == "week2":
        return "even"
    return "both"


def _map_lesson_type(raw: str, subject: str = "") -> str:
    text = clean_text(raw).lower()
    if "физическая культура" in (subject or "").lower() or "физкультур" in (subject or "").lower():
        return "physical"
    mapping = {
        "лекция": "lecture", "семинар": "seminar", "лабораторная": "lab", "лаб": "lab",
        "физкультура": "physical", "физра": "physical",
        "экзамен": "exam", "зачёт": "other", "зачет": "other",
        "консультация": "other", "практика": "seminar", "практическ": "seminar",
    }
    for key, value in mapping.items():
        if key in text:
            return value
    return "other"


def _time_range(time_str: str) -> tuple[str, str]:
    """Извлекает (start, end) HH:MM из строки вида '3 пара (13:00—14:30)'."""
    if not time_str:
        return ("09:00", "10:30")
    times = [t.zfill(5) for t in re.findall(r"\d{1,2}:\d{2}", time_str)]  # "9:30" -> "09:30" (иначе ломается сортировка)
    if len(times) >= 2:
        return (times[0], times[1])
    if len(times) == 1:
        start = times[0]
        try:
            end = (datetime.strptime(start, "%H:%M") + timedelta(minutes=90)).strftime("%H:%M")
        except ValueError:
            end = "10:30"
        return (start, end)
    return ("09:00", "10:30")


WEEKDAY_RU_TO_INT = {
    "Понедельник": 0, "Вторник": 1, "Среда": 2, "Четверг": 3,
    "Пятница": 4, "Суббота": 5, "Воскресенье": 6,
}


def save_guap_schedule(db: Session, user: User, group_name: str, replace: bool = True) -> list[dict]:
    """Парсит расписание ГУАП по номеру группы и сохраняет занятия в БД пользователя.

    Если replace=True (по умолчанию), предварительно удаляет все текущие занятия,
    так как официальное расписание становится основным источником расписания.
    Возвращает список сохранённых занятий.
    """
    logger.info("Начало парсинга расписания для пользователя %s, группа %s", user.id, group_name)
    data = get_guap_schedule_by_name(group_name)
    if not data:
        logger.warning("Расписание для группы %s не получено (пусто или ошибка сайта).", group_name)
        return []
    if replace:
        deleted = db.query(Lesson).filter_by(user_id=user.id).delete()
        logger.info("Удалено %d старых занятий пользователя %s.", deleted, user.id)
    markers = {}
    for _lessons in data.values():
        for _l in _lessons:
            key = (_l.get("week_class", ""), _l.get("week", ""))
            markers[key] = markers.get(key, 0) + 1
    logger.info("Найденные маркеры недели (класс, title) -> кол-во: %s", markers)
    seen = set()
    saved = []
    total_lessons = 0
    skipped_groups = 0
    for day_name, lessons in data.items():
        weekday = WEEKDAY_RU_TO_INT.get(day_name)
        if weekday is None:
            continue
        for lesson in lessons:
            total_lessons += 1
            groups = lesson.get("groups") or []
            # Если у пары указаны конкретные группы и нашей нет — это не потоковая лекция, пропускаем
            if groups and group_name not in groups:
                skipped_groups += 1
                continue
            start_time, end_time = _time_range(lesson.get("time", ""))
            dedupe_key = (weekday, start_time, end_time, lesson.get("subject", ""), lesson.get("type", ""),
                          lesson.get("week", ""), lesson.get("week_class", ""))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            week_parity = parse_week_parity(lesson.get("week", ""), lesson.get("week_class", ""))
            row = Lesson(
                user_id=user.id,
                subject=lesson.get("subject") or "Занятие",
                lesson_type=_map_lesson_type(lesson.get("type", ""), lesson.get("subject", "")),
                weekday=weekday,
                start_time=start_time,
                end_time=end_time,
                room=lesson.get("location", "") or "",
                campus=lesson.get("department", "") or "",
                week_parity=week_parity,
                notes=("Спарсено из расписания ГУАП, группа " + group_name +
                       ("; преподаватель: " + lesson.get("teacher", "") if lesson.get("teacher") else "")),
                active=True,
            )
            db.add(row)
            saved.append({
                "subject": row.subject, "type": row.lesson_type, "weekday": row.weekday,
                "start": row.start_time, "end": row.end_time, "room": row.room,
                "campus": row.campus, "week_parity": row.week_parity,
            })
    db.commit()
    logger.info("Сохранено %d занятий из %d (пропущено по группам: %d) для пользователя %s, группа %s",
                len(saved), total_lessons, skipped_groups, user.id, group_name)
    return saved