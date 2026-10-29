# Архитектура StudyPilot

```text
Telegram Bot ─────┐
                  ├── MySQL
Telegram Mini App ── FastAPI ── Agent Orchestrator ── Gemini API (optional)
                       ├── Schedule service
                       ├── Bag rules service
                       ├── Windows/departure calculator
                       └── Open-Meteo adapter
```

## Принципы
- API и бот используют одну базу данных.
- Telegram Mini App отправляет `initData`; backend проверяет подпись и срок действия.
- Расписание, расчёт выхода, подбор вещей и поиск окон выполняются детерминированным кодом.
- LLM помогает интерпретировать свободный запрос и выбрать инструмент, но не является источником фактов.
- Внешние API имеют таймауты; сбой погоды не должен ломать расписание.

## Основные таблицы
- `users`: Telegram ID, имя, часовой пояс, адрес/город, параметры дороги.
- `lessons`: предмет, тип, день недели, время, аудитория, корпус, чётность недели.
- `bag_rules`: условие применения и список вещей.
