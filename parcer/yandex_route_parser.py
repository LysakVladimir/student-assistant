"""Парсер маршрутов Яндекс Карт через браузер Playwright.

Скрипт не использует платный Routing API: он открывает обычную страницу
Яндекс Карт и читает отображаемые на ней данные.

Установка:
    pip install playwright
    playwright install chromium

Запуск:
    python yandex_route_parser.py
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

MAPS_URL = "https://yandex.ru/maps/"
TRANSPORTS = {
    "1": {"name": "автомобиль", "rtt": "auto"},
    "2": {"name": "общественный транспорт", "rtt": "mt"},
}

DURATION_RE = re.compile(
    r"(?<!\d)(?:(?P<h>\d+)\s*(?:ч|час(?:а|ов)?)\.?"
    r"(?:\s*(?P<m>\d+)\s*(?:мин|минут(?:а|ы)?)\.?)?"
    r"|(?P<only_m>\d+)\s*(?:мин|минут(?:а|ы)?)\.?)(?!\d)",
    re.IGNORECASE,
)

# Строгие шаблоны заголовков транспортных этапов Яндекс Карт.
# Для наземного транспорта сохраняем номер маршрута.
ROUTE_NUMBER = r"(?P<number>\d+[A-Za-zА-Яа-я]?)"
GROUND_SEGMENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "автобус",
        re.compile(
            rf"^(?:на\s+)?автобус(?:е)?\s*(?:№\s*)?{ROUTE_NUMBER}$",
            re.IGNORECASE,
        ),
    ),
    (
        "автобус",
        re.compile(rf"^{ROUTE_NUMBER}\s*автобус(?:е)?$", re.IGNORECASE),
    ),
    (
        "трамвай",
        re.compile(
            rf"^(?:на\s+)?трамва(?:й|е)\s*(?:№\s*)?{ROUTE_NUMBER}$",
            re.IGNORECASE,
        ),
    ),
    (
        "трамвай",
        re.compile(rf"^{ROUTE_NUMBER}\s*трамва(?:й|е)$", re.IGNORECASE),
    ),
    (
        "троллейбус",
        re.compile(
            rf"^(?:на\s+)?троллейбус(?:е)?\s*(?:№\s*)?{ROUTE_NUMBER}$",
            re.IGNORECASE,
        ),
    ),
    (
        "троллейбус",
        re.compile(rf"^{ROUTE_NUMBER}\s*троллейбус(?:е)?$", re.IGNORECASE),
    ),
]

OTHER_SEGMENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "маршрутка",
        re.compile(
            r"^(?:на\s+)?(?:маршрутка|маршрутное\s+такси)(?:\s*(?:№\s*)?\d+[A-Za-zА-Яа-я]?)?$",
            re.IGNORECASE,
        ),
    ),
    (
        "метро",
        re.compile(
            r"^(?:на\s+)?метро(?:\s+\d+\s+линия)?(?:\s*[–—-]\s*.+)?$",
            re.IGNORECASE,
        ),
    ),
    (
        "метро",
        re.compile(r"^\d+\s+линия\s*[–—-]\s*.+$", re.IGNORECASE),
    ),
    (
        "электричка",
        re.compile(r"^(?:на\s+)?(?:электричка|электричке|пригородный\s+поезд)(?:\s+.+)?$", re.IGNORECASE),
    ),
    ("МЦК", re.compile(r"^(?:на\s+)?МЦК(?:\s+.+)?$", re.IGNORECASE)),
    ("МЦД", re.compile(r"^(?:на\s+)?МЦД(?:\s+.+)?$", re.IGNORECASE)),
    (
        "аэроэкспресс",
        re.compile(r"^(?:на\s+)?аэроэкспресс(?:\s+.+)?$", re.IGNORECASE),
    ),
    (
        "водный транспорт",
        re.compile(r"^(?:водный транспорт|речной трамвай|паром)(?:\s+.+)?$", re.IGNORECASE),
    ),
]

GROUND_MODES = {"автобус", "трамвай", "троллейбус"}

ROUTE_SUMMARY_RE = re.compile(
    r"подробный\s+маршрут\s*(.*?)(?=проезд\s*:|исправить\s+неточность|$)",
    re.IGNORECASE | re.DOTALL,
)
ROUTE_ALTERNATIVES_RE = re.compile(r"(?:^|\n)\s*ещё\s+варианты\b", re.IGNORECASE)
WAIT_INLINE_RE = re.compile(r"подождать\s*:?[\s\u00a0]*(?P<value>\d{1,3})[\s\u00a0]*(?:мин(?:ут(?:а|ы)?)?)?", re.IGNORECASE)

# Слова, характерные для подробностей маршрута (остановки, станции,
# пересадки и шаги пешком). Используются только для выбора блока деталей.
DETAIL_CONTEXT_RE = re.compile(
    r"остановк|станци|пересад|пешком|пройти|выход\s+из|выйти\s+на|"
    r"направлени|до\s+остановки|маршрут",
    re.IGNORECASE,
)


def read_point(prompt: str) -> tuple[float, float]:
    """Запросить координаты в порядке широта,долгота."""
    while True:
        raw = input(prompt).strip().replace(";", ",")
        try:
            lat_text, lon_text = [part.strip() for part in raw.split(",", maxsplit=1)]
            lat, lon = float(lat_text), float(lon_text)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
            return lat, lon
        except (ValueError, TypeError):
            print("Введите координаты в формате широта,долгота. Например: 59.941385,30.467925")


def try_get_browser_location(page) -> tuple[float, float] | None:
    """Попытаться получить геолокацию через браузер; при неудаче вернуть None."""
    try:
        page.goto(MAPS_URL, wait_until="domcontentloaded", timeout=45_000)
        parsed = page.url.split("/", 3)
        origin = f"{parsed[0]}//{parsed[2]}" if len(parsed) > 2 else "https://yandex.ru"
        page.context.grant_permissions(["geolocation"], origin=origin)

        result = page.evaluate(
            """() => new Promise((resolve) => {
                if (!navigator.geolocation) {
                    resolve({ok: false, error: 'Geolocation API недоступен'});
                    return;
                }
                navigator.geolocation.getCurrentPosition(
                    (position) => resolve({
                        ok: true,
                        lat: position.coords.latitude,
                        lon: position.coords.longitude,
                        accuracy: position.coords.accuracy
                    }),
                    (error) => resolve({ok: false, error: error.message, code: error.code}),
                    { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 }
                );
            })""",
            timeout=20_000,
        )

        if result.get("ok"):
            lat, lon = float(result["lat"]), float(result["lon"])
            print(f"Геолокация получена: {lat:.6f}, {lon:.6f}")
            print(f"Точность определения: примерно {round(result.get('accuracy', 0))} м")
            return lat, lon

        print(f"Браузер не смог определить местоположение: {result.get('error', 'неизвестная ошибка')}")
    except Exception as exc:
        print(f"Не удалось получить геолокацию автоматически: {exc}")

    return None


def generate_route_url(
    point_a: tuple[float, float],
    point_b: tuple[float, float],
    transport: str,
) -> str:
    """Создать ссылку Яндекс Карт. Координаты передаются как широта,долгота."""
    if transport not in TRANSPORTS:
        raise ValueError("Транспорт должен быть 1 (автомобиль) или 2 (общественный транспорт)")

    params = {
        "mode": "routes",
        "rtext": f"{point_a[0]},{point_a[1]}~{point_b[0]},{point_b[1]}",
        "rtt": TRANSPORTS[transport]["rtt"],
    }
    return f"{MAPS_URL}?{urlencode(params)}"


def format_duration(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours} ч {mins} мин"
    if hours:
        return f"{hours} ч"
    return f"{mins} мин"


def extract_duration(page_text: str) -> str | None:
    """Извлечь первую длительность (логику времени пока не меняем)."""
    match = DURATION_RE.search(page_text)
    if not match:
        return None

    if match.group("only_m"):
        total_minutes = int(match.group("only_m"))
    else:
        total_minutes = int(match.group("h") or 0) * 60 + int(match.group("m") or 0)

    return format_duration(total_minutes) if total_minutes > 0 else None


def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" \t\u00a0\u200b")


def extract_route_summary(details_text: str) -> str:
    """Извлечь компактную последовательность этапов выбранного маршрута."""
    match = ROUTE_SUMMARY_RE.search(details_text)
    if match:
        return match.group(1).strip()
    return ""


@dataclass
class RouteSegment:
    """Один распознанный участок общественного транспорта."""

    mode: str
    number: str | None = None
    source_line: str = ""
    waiting_minutes: int | None = None


def _match_ground_segment(line: str) -> tuple[str, str] | None:
    """Вернуть (вид транспорта, номер), если строка — заголовок наземного этапа."""
    for mode, pattern in GROUND_SEGMENT_PATTERNS:
        match = pattern.fullmatch(line)
        if match:
            number = match.groupdict().get("number")
            if number:
                return mode, number
    return None


def _match_transit_segment(line: str) -> tuple[str, str | None] | None:
    """Распознать любой заголовок транспорта: наземный, метро и др."""
    ground = _match_ground_segment(line)
    if ground:
        return ground
    for mode, pattern in OTHER_SEGMENT_PATTERNS:
        if pattern.fullmatch(line):
            return mode, None
    return None


def extract_route_segments(details_text: str) -> tuple[list[RouteSegment], list[str]]:
    """Распознать транспортные этапы только в сводке выбранного маршрута."""
    summary = extract_route_summary(details_text)
    source_text = summary or details_text

    if not summary:
        alternatives = ROUTE_ALTERNATIVES_RE.search(source_text)
        if alternatives:
            source_text = source_text[:alternatives.start()]

    segments: list[RouteSegment] = []
    matched_lines: list[str] = []

    # Не удаляем повторы: один и тот же номер может встретиться в разных этапах пути.
    for raw_line in source_text.splitlines():
        line = normalize_line(raw_line)
        if not line:
            continue

        ground = _match_ground_segment(line)
        if ground:
            mode, number = ground
            segments.append(RouteSegment(mode=mode, number=number, source_line=line))
            matched_lines.append(line)
            continue

        for mode, pattern in OTHER_SEGMENT_PATTERNS:
            if pattern.fullmatch(line):
                segments.append(RouteSegment(mode=mode, source_line=line))
                matched_lines.append(line)
                break

    return segments, matched_lines


def extract_waiting_times(details_text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Связать «Подождать N мин» с ближайшим предыдущим этапом транспорта.

    Сканируется текст подробностей выбранного маршрута. После заголовка любого
    транспортного этапа ищется соответствующая строка ожидания. Пешие участки
    сбрасывают предыдущий этап, чтобы не привязать ожидание к неверному транспорту.
    """
    events: list[dict[str, Any]] = []
    matched_lines: list[str] = []
    active_transit: tuple[str, str | None] | None = None
    lines = [normalize_line(line) for line in details_text.splitlines()]

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue

        transit_segment = _match_transit_segment(line)
        if transit_segment:
            active_transit = transit_segment
            i += 1
            continue

        # Пешая часть маршрута завершает предыдущий транспортный этап.
        if re.match(r"^(?:пешком\b|пройти\b|выход\b|дальше\b|\d+\s*(?:мин|м)\s+пешком)", line, re.IGNORECASE):
            active_transit = None
            i += 1
            continue

        wait_match = WAIT_INLINE_RE.search(line)
        if not wait_match and line.lower().startswith("подождать") and i + 1 < len(lines):
            next_line = lines[i + 1]
            duration_match = re.search(r"(?<!\d)(?P<value>\d{1,3})\s*(?:мин(?:ут(?:а|ы)?)?)?", next_line, re.IGNORECASE)
            if duration_match:
                wait_match = duration_match
                i += 1

        if wait_match and active_transit:
            minutes = int(wait_match.group("value"))
            mode, number = active_transit
            events.append({
                "mode": mode,
                "number": number,
                "waiting_minutes": minutes,
                "source_line": line if "подождать" in line.lower() else f"Подождать {lines[i]}",
            })
            matched_lines.append(line)
            # Один этап получает ровно одно ожидание.
            active_transit = None

        i += 1

    return events, matched_lines


def attach_waiting_times(
    segments: list[RouteSegment], events: list[dict[str, Any]]
) -> None:
    """Проставить ожидание этапам в порядке следования маршрута."""
    queues: dict[tuple[str, str], list[int]] = {}
    for event in events:
        key = (str(event["mode"]), str(event["number"] or "").upper())
        queues.setdefault(key, []).append(int(event["waiting_minutes"]))

    for segment in segments:
        key = (segment.mode, (segment.number or "").upper())
        values = queues.get(key)
        if values:
            segment.waiting_minutes = values.pop(0)

def extract_modes_from_segment_lines(details_text: str) -> tuple[list[str], list[str]]:
    """Совместимая обёртка для скоринга DOM-кандидатов."""
    segments, matched_lines = extract_route_segments(details_text)
    modes = list(dict.fromkeys(segment.mode for segment in segments))
    return modes, matched_lines


def collect_route_detail_candidates(page) -> list[dict]:
    """Получить текст видимых блоков, похожих на панель маршрута.

    Мы намеренно не используем body.innerText для определения транспорта:
    в нём есть названия остановок, рекомендации и другие варианты маршрутов.
    """
    return page.evaluate(
        r"""() => {
            const selector = [
                'aside', '[role="main"]', '[role="complementary"]',
                '[role="dialog"]', '[data-testid*="route" i]',
                '[class*="route" i]', '[class*="masstransit" i]',
                '[class*="transport" i]', '[class*="details" i]'
            ].join(',');
            const unique = new Set(document.querySelectorAll(selector));
            const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 &&
                    s.display !== 'none' && s.visibility !== 'hidden';
            };
            const out = [];
            for (const el of unique) {
                if (!visible(el)) continue;
                const text = (el.innerText || '').trim();
                // Не берём целую страницу и слишком мелкие элементы.
                if (text.length < 25 || text.length > 12000) continue;
                const cls = typeof el.className === 'string' ? el.className : '';
                out.push({
                    tag: el.tagName.toLowerCase(),
                    role: el.getAttribute('role') || '',
                    aria: el.getAttribute('aria-label') || '',
                    testid: el.getAttribute('data-testid') || '',
                    class_name: cls.slice(0, 300),
                    text: text.slice(0, 12000)
                });
            }
            return out;
        }"""
    )


def score_detail_candidate(candidate: dict) -> tuple[int, int]:
    text = candidate.get("text", "")
    modes, _ = extract_modes_from_segment_lines(text)
    score = len(modes) * 30

    tag = candidate.get("tag", "")
    role = candidate.get("role", "")
    metadata = " ".join(
        str(candidate.get(key, ""))
        for key in ("aria", "testid", "class_name")
    ).lower()

    if tag == "aside":
        score += 12
    if "подробный маршрут" in text.lower():
        score += 45
    if "проезд:" in text.lower():
        score += 12
    if role in {"main", "complementary", "dialog"}:
        score += 8
    if any(word in metadata for word in ("route", "masstransit", "transport", "detail")):
        score += 10

    context_hits = len(DETAIL_CONTEXT_RE.findall(text))
    score += min(context_hits, 6) * 2

    # Предпочитаем компактную панель подробностей огромным контейнерам.
    length = len(text)
    if length > 7000:
        score -= 15
    elif length > 4000:
        score -= 8

    return score, -length


def select_route_details(candidates: list[dict]) -> tuple[str, dict | None]:
    """Выбрать наиболее вероятный блок подробностей выбранного маршрута."""
    ranked = sorted(candidates, key=score_detail_candidate, reverse=True)
    for candidate in ranked:
        modes, _ = extract_modes_from_segment_lines(candidate.get("text", ""))
        if modes:
            return candidate["text"], candidate
    return "", ranked[0] if ranked else None


def open_route_details(page) -> bool:
    """Открыть именно подробности маршрута, если они доступны в боковой панели."""
    labels = [
        re.compile(r"^Посмотреть подробнее$", re.IGNORECASE),
        re.compile(r"^Подробнее$", re.IGNORECASE),
        re.compile(r"^Детали маршрута$", re.IGNORECASE),
        re.compile(r"^Показать подробности$", re.IGNORECASE),
    ]

    for pattern in labels:
        locator = page.get_by_text(pattern, exact=True)
        try:
            count = min(locator.count(), 8)
        except Exception:
            continue

        for index in range(count):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible(timeout=500):
                    candidate.click(timeout=2_000)
                    page.wait_for_timeout(1_500)
                    return True
            except Exception:
                continue
    return False


def save_debug(page, page_text: str, candidates: list[dict] | None = None) -> None:
    """Сохранить диагностические данные для адаптации к актуальному DOM Яндекса."""
    debug_dir = Path("yandex_debug")
    debug_dir.mkdir(exist_ok=True)
    (debug_dir / "page_text.txt").write_text(page_text, encoding="utf-8")

    if candidates is not None:
        (debug_dir / "route_candidates.json").write_text(
            json.dumps(candidates, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    try:
        page.screenshot(path=str(debug_dir / "page.png"), full_page=True)
    except Exception:
        pass

    print(f"Диагностика сохранена в папку: {debug_dir.resolve()}")



def format_waiting_minutes(minutes: int) -> str:
    """Форматировать минуты с корректным русским окончанием."""
    last_two = minutes % 100
    if 11 <= last_two <= 14:
        word = "минут"
    elif minutes % 10 == 1:
        word = "минута"
    elif 2 <= minutes % 10 <= 4:
        word = "минуты"
    else:
        word = "минут"
    return f"{minutes} {word}"


def format_transport_description(segments: list[RouteSegment]) -> str:
    """Сформировать описание этапов и времени ожидания из Яндекс Карт."""
    parts: list[str] = []
    for segment in segments:
        if segment.mode in GROUND_MODES and segment.number:
            label = f"{segment.mode} {segment.number}"
        else:
            label = segment.mode
        if segment.waiting_minutes is not None:
            label += f" (ожидание ~{format_waiting_minutes(segment.waiting_minutes)})"
        parts.append(label)
    return ", ".join(parts) if parts else "общественный транспорт (этапы не распознаны)"

def parse_route(page, route_url: str, transport: str) -> tuple[str, str]:
    page.goto(route_url, wait_until="domcontentloaded", timeout=60_000)

    try:
        page.wait_for_function(
            r"""() => {
                const text = document.body?.innerText || '';
                return /\d+\s*(?:мин|минут|ч|час)/i.test(text);
            }""",
            timeout=60_000,
        )
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(4_000)
    open_route_details(page)
    page.wait_for_timeout(1_500)

    page_text = page.locator("body").inner_text(timeout=15_000)
    duration = extract_duration(page_text)

    candidates = collect_route_detail_candidates(page)
    if not duration:
        save_debug(page, page_text, candidates)
        raise RuntimeError(
            "Не удалось найти длительность маршрута на странице. "
            "Текст страницы и кандидаты DOM сохранены в yandex_debug."
        )

    if transport == "1":
        transport_description = "автомобиль"
        details_text, selected_candidate = select_route_details(candidates)
        segments: list[RouteSegment] = []
        matched_lines: list[str] = []
        waiting_events: list[dict[str, Any]] = []
        waiting_lines: list[str] = []
    else:
        details_text, selected_candidate = select_route_details(candidates)
        segments, matched_lines = extract_route_segments(details_text)
        waiting_events, waiting_lines = extract_waiting_times(details_text)
        attach_waiting_times(segments, waiting_events)
        transport_description = format_transport_description(segments)

        if not segments:
            print(
                "Не удалось достоверно распознать этапы маршрута. "
                "Проверьте yandex_debug/transport_detection.json и route_candidates.json."
            )
        elif any(
            segment.mode in GROUND_MODES and segment.number and segment.waiting_minutes is None
            for segment in segments
        ):
            print(
                "Внимание: для некоторых наземных этапов Яндекс не показал время ожидания. "
                "В результате такое ожидание не указано; подробности сохранены в диагностике."
            )

    debug_dir = Path("yandex_debug")
    debug_dir.mkdir(exist_ok=True)
    diagnostics = {
        "selected_candidate": selected_candidate,
        "source_used": "route_summary" if extract_route_summary(details_text) else "detail_block_fallback",
        "route_summary_text": extract_route_summary(details_text),
        "matched_segment_lines": matched_lines,
        "detected_segments": [asdict(segment) for segment in segments],
        "waiting_events": waiting_events,
        "matched_waiting_lines": waiting_lines,
        "waiting_time_source": "Яндекс Карты: строка «Подождать N мин» после соответствующего транспортного этапа",
        "external_transport_portal_used": False,
    }
    (debug_dir / "transport_detection.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    save_debug(page, page_text, candidates)

    return duration, transport_description

def main() -> int:
    print("=== Парсер маршрутов Яндекс Карт ===")
    print("Для работы потребуется установленный Chromium от Playwright.\n")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(
            locale="ru-RU",
            viewport={"width": 1440, "height": 1000},
        )
        page = context.new_page()

        try:
            point_a = try_get_browser_location(page)
            if point_a is None:
                print("\nВведите начальные координаты вручную.")
                point_a = read_point("Точка А (широта,долгота): ")

            print("\nВведите координаты места назначения.")
            point_b = read_point("Точка Б (широта,долгота): ")

            while True:
                transport = input("\nТранспорт (1 — автомобиль, 2 — общественный транспорт): ").strip()
                if transport in TRANSPORTS:
                    break
                print("Нужно выбрать 1 или 2.")

            route_url = generate_route_url(point_a, point_b, transport)
            print("\nОткрываю маршрут в Яндекс Картах...")
            print(route_url)

            duration, transport_description = parse_route(page, route_url, transport)

            print("\n=== Результат ===")
            print(f"Твой маршрут займет {duration}.")
            print(f"Включает в себя: {transport_description}.")
            print(f"Ссылка на маршрут: {route_url}")

            input("\nНажмите Enter, чтобы закрыть браузер...")
            return 0

        except KeyboardInterrupt:
            print("\nРабота прервана пользователем.")
            return 130
        except Exception as exc:
            print(f"\nОшибка: {exc}", file=sys.stderr)
            return 1
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
