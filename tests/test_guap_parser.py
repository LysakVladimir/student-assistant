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


def test_city_must_be_in_russian():
    import pytest
    from pydantic import ValidationError
    from backend.app.schemas import UserPatch
    assert UserPatch(home_address=" Санкт-Петербург ").home_address == "Санкт-Петербург"
    assert UserPatch(home_address="").home_address == ""
    with pytest.raises(ValidationError):
        UserPatch(home_address="Moscow")


def test_weather_forecast_parsing(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import backend.app.services as svc

    class Resp:
        def __init__(self, data): self._d = data
        def raise_for_status(self): pass
        def json(self): return self._d

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None):
            if "geocoding" in url:
                assert params["language"] == "ru" and params["countryCode"] == "RU"
                return Resp({"results": [{"name": "Санкт-Петербург", "admin1": "Санкт-Петербург", "latitude": 59.9, "longitude": 30.3}]})
            times = [f"2026-11-12T{h:02d}:00" for h in range(24)] + [f"2026-11-13T{h:02d}:00" for h in range(24)]
            return Resp({
                "current": {"time": "2026-11-12T10:15", "temperature_2m": 2.4, "apparent_temperature": -1.0, "precipitation": 0.4,
                            "weather_code": 61, "wind_speed_10m": 6.0, "relative_humidity_2m": 88},
                "hourly": {"time": times, "temperature_2m": [1.0] * 48, "precipitation_probability": [40] * 48, "weather_code": [3] * 48},
                "daily": {"time": ["2026-11-12", "2026-11-13", "2026-11-14"], "weather_code": [61, 3, 0],
                          "temperature_2m_max": [3, 4, 5], "temperature_2m_min": [0, 1, 2], "precipitation_probability_max": [80, 30, 10]},
            })

    monkeypatch.setattr(svc.httpx, "AsyncClient", FakeClient)
    user = SimpleNamespace(home_address="Санкт-Петербург", timezone="Europe/Moscow")
    r = asyncio.run(svc.get_weather_forecast(user))
    assert r["available"] and r["place"] == "Санкт-Петербург"
    assert r["current"]["label"] == "Небольшой дождь"
    assert r["hours"][0]["time"] == "10:00" and len(r["hours"]) == 8
    assert [d["weekday"] for d in r["days"]] == ["Четверг", "Пятница", "Суббота"]
    assert "Возьмите зонт или дождевик" in r["advice"]

    empty = asyncio.run(svc.get_weather_forecast(SimpleNamespace(home_address="", timezone="Europe/Moscow")))
    assert empty["available"] is False
