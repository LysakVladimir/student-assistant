from datetime import date

from backend.app.services import parse_week_parity, parse_schedule_html, current_week_parity


def test_parity_titles_odd_is_not_even():
    # Регрессия: «нечетная» содержит «четная» — раньше нечётные пары попадали в чётные.
    assert parse_week_parity("Нечетная неделя") == "odd"
    assert parse_week_parity("Нечётная неделя") == "odd"
    assert parse_week_parity("Четная неделя") == "even"
    assert parse_week_parity("Чётная неделя") == "even"
    assert parse_week_parity("") == "both"


def test_parity_falls_back_to_css_class():
    assert parse_week_parity("", "week1") == "odd"
    assert parse_week_parity("", "week2") == "even"
    # title важнее класса
    assert parse_week_parity("Четная неделя", "week1") == "even"


def _lesson(time_header, marker, subject):
    return f'''
    <div class="mt-3 text-danger">{time_header}</div>
    <div class="mb-3 py-2 d-flex">
      {marker}
      <div>
        <div class="fs-6 lh-sm opacity-50">ЛК</div>
        <div class="lead lh-sm">{subject}</div>
        <div class="opacity-75"><a href="?ad=1">Б.Морская, 67 – 11-11</a> <a href="?gr=1">7103</a></div>
      </div>
    </div>'''


def test_schedule_html_marks_odd_even_and_every_week():
    html = f'''<div class="container content mb-5">
      <h4 class="text-danger">Понедельник</h4>
      {_lesson("1 пара (09:30—11:00)", '<div class="week1" title="Нечетная неделя">▲</div>', "Физика")}
      {_lesson("2 пара (11:10—12:40)", '<div class="week2" title="Четная неделя">▼</div>', "Химия")}
      {_lesson("3 пара (13:00—14:30)", "", "Математика")}
    </div>'''
    data = parse_schedule_html(html, "7103")
    lessons = data["Понедельник"]
    assert [(l["subject"], parse_week_parity(l["week"], l["week_class"])) for l in lessons] == [
        ("Физика", "odd"), ("Химия", "even"), ("Математика", "both"),
    ]


def test_week_parity_alternates_and_uses_requested_date():
    ref = date(2026, 8, 31)  # понедельник, нечётная неделя
    assert current_week_parity(date(2026, 9, 6), ref) == "odd"    # воскресенье той же недели
    assert current_week_parity(date(2026, 9, 7), ref) == "even"   # «завтра» из воскресенья — уже другая неделя
    assert current_week_parity(date(2026, 9, 14), ref) == "odd"


def test_real_guap_page_group_4414():
    """Реальная страница guap.ru/rasp?gr=7103 (сохранена 12.11.2026)."""
    from pathlib import Path
    from backend.app.services import _map_lesson_type, _time_range
    html = (Path(__file__).parent / "fixtures" / "guap_7103.html").read_text(encoding="utf-8")
    data = parse_schedule_html(html, "4414")
    par = [parse_week_parity(l["week"], l["week_class"]) for ls in data.values() for l in ls]
    assert par.count("odd") == 7 and par.count("even") == 5 and par.count("both") == 6
    assert _time_range("4 пара (9:30—11:00)") == ("09:30", "11:00")
    assert _map_lesson_type("Практическое занятие", "Прикладная физическая культура") == "physical"
    assert _map_lesson_type("Практическое занятие", "Введение в анализ данных") == "seminar"
