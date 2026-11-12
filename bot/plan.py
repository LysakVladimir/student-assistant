import os
from datetime import date, timedelta, datetime
from app_models import Lesson, BagRule
TYPES={"lecture":"лекция","seminar":"семинар","lab":"лабораторная","physical":"физкультура","exam":"экзамен","other":"занятие"}
DAYS=["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]

def week_parity(on: date) -> str:
    """"odd"/"even" — та же логика, что в backend (ODD_WEEK_REFERENCE = любая дата нечётной недели)."""
    ref = None
    raw = os.getenv("ODD_WEEK_REFERENCE", "").strip()
    if raw:
        try: ref = date.fromisoformat(raw)
        except ValueError: ref = None
    if ref is None:
        year = on.year if on >= date(on.year, 9, 1) else on.year - 1
        ref = date(year, 9, 1)
    weeks = ((on - timedelta(days=on.weekday())) - (ref - timedelta(days=ref.weekday()))).days // 7
    return "odd" if weeks % 2 == 0 else "even"

def plan_text(db, user, day="today"):
    target=date.today()+(timedelta(days=1) if day=="tomorrow" else timedelta())
    parity=week_parity(target)
    rows=db.query(Lesson).filter_by(user_id=user.id, weekday=target.weekday(), active=True).order_by(Lesson.start_time).all()
    lessons=[l for l in rows if l.week_parity in ("both", parity)]
    lines=[f"📅 План на {DAYS[target.weekday()]}, {target:%d.%m} ({'нечётная' if parity=='odd' else 'чётная'} неделя)"]
    if not lessons:
        lines.append("Занятий в расписании нет.")
    else:
        for l in lessons: lines.append(f"• {l.start_time}–{l.end_time} {l.subject} ({TYPES.get(l.lesson_type,l.lesson_type)}) {l.room}")
    bag=set()
    for r in db.query(BagRule).filter_by(user_id=user.id, enabled=True).all():
        if r.match_type=="always" or any((r.match_type=="type" and l.lesson_type==r.match_value) or (r.match_type=="keyword" and r.match_value.lower() in l.subject.lower()) for l in lessons):
            bag.update(x.strip() for x in r.items.split(",") if x.strip())
    for l in lessons:
        if l.lesson_type=="physical": bag.update(["спортивная форма","спортивная обувь"])
        if l.lesson_type=="lab": bag.update(["методичка","тетрадь"])
        if l.lesson_type=="exam": bag.update(["студенческий билет","ручки"])
    lines += ["", "🎒 Рюкзак:", "• "+("\n• ".join(sorted(bag)) if bag else "правила не настроены")]
    windows=[]
    for a,b in zip(lessons,lessons[1:]):
        mins=int((datetime.strptime(b.start_time,"%H:%M")-datetime.strptime(a.end_time,"%H:%M")).total_seconds()/60)
        if mins>=40: windows.append(f"{a.end_time}–{b.start_time} ({mins} мин.)")
    lines += ["", "🪟 Окна:", "• "+("\n• ".join(windows) if windows else "не обнаружены")]
    if lessons:
        start=datetime.strptime(lessons[0].start_time,"%H:%M")
        leave=(start-timedelta(minutes=user.travel_minutes+user.prep_minutes+user.buffer_minutes)).strftime("%H:%M")
        lines += ["",f"🚪 Время выхода: {leave}","", "⚠️ Расчёт основан на заданном времени пути, без реальных данных о пробках."]
    return "\n".join(lines)
