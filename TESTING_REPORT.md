# Отчёт о тестировании StudyPilot AI-agent

> Актуализация после диагностики реальных Telegram/Polza-сбоев: подробные причины и статусы находятся в `AI_DEBUG_REPORT.md`.

Дата: 22 ноября 2026. Среда: Windows, локальный checkout `C:\Projects\student-assistant`, ветка `feature/telegram-ai-agent`.

Статусы: PASS — проверка реально выполнена; FAIL — обнаружена ошибка; BLOCKED — внешняя зависимость недоступна; NOT TESTED — проверка не запускалась.

## Выполненные команды

- `.\.venv\Scripts\python.exe -m compileall -q backend bot tests` — PASS.
- `.\.venv\Scripts\python.exe -m pytest -q` — PASS: 26 тестов, 148 предупреждений (в основном о будущем удалении `datetime.utcnow`); ошибок нет.
- `npm audit --audit-level=high` — PASS: после обновления до Vite 7.3.8 и plugin-react 5.2.0 найдено 0 уязвимостей.
- `npm run build` — PASS: Vite 7.3.8 собрал production bundle, 33 модуля.
- FastAPI `TestClient`, `GET /health` с временной SQLite — PASS: HTTP 200, `{"status":"ok"}`.
- Импорт bot с тестовым токеном/SQLite — PASS: зарегистрировано 19 message handlers и 1 edited-message handler; обращения к Telegram не выполнялись.
- `docker version` и `docker compose config --quiet` — BLOCKED: команда `docker` отсутствует в окружении.

## Матрица функций

| Функция | Метод | Ожидание | Результат | Статус |
|---|---|---|---|---|
| Синтаксис/import Python | compileall, import bot | Нет syntax/import ошибок | Выполнено | PASS |
| Старые расчёты и окна | pytest | Регрессии отсутствуют | Тесты прошли | PASS |
| Парсер ГУАП | fixture реальной страницы + pytest | Корректные пары/чётность | Тесты прошли | PASS |
| Погода | mock Open-Meteo | Парсинг и рекомендации | Тест прошёл | PASS |
| Дедупликация сообщения | SQLite unit test, повтор одного `(chat,id)` | Одна запись, текст обновлён | Подтверждено | PASS |
| Выделение задачи без API | SQLite unit test | Создан task fallback | Подтверждено | PASS |
| Поиск/RAG isolation | Два пользователя и два чата | Чужой чат не возвращается | Подтверждено | PASS |
| Monitor cooldown | Два совпадения подряд | Только первое уведомление | Подтверждено | PASS |
| Frontend AI UI | Vite production build | Успешная сборка | Выполнено | PASS |
| FastAPI health | TestClient + SQLite | HTTP 200 | Выполнено | PASS |
| Реальная MySQL и миграция | Docker Compose | Таблицы созданы без потери данных | Docker недоступен | BLOCKED |
| Docker images/health/logs | Docker Compose | 4 сервиса работают | Docker недоступен | BLOCKED |
| Реальный Telegram `/start` | Telegram API | Регистрация и ответ | Нет разрешённого live-сеанса | BLOCKED |
| Группа `/ai_on`, права admin | Telegram API | Только admin активирует | Код/обработчики проверены, live API нет | BLOCKED |
| Text/reply/edit/attachments | Telegram API | Updates сохранены | Unit охватывает ingest; live updates нет | BLOCKED |
| Voice/image/document extraction | Polza Flash images; optional Gemini audio | Транскрипция/извлечение | Очередь/ошибки проверены локально; live media API нет | BLOCKED |
| Polza embeddings/RAG | mock + BGE-M3 contract | Семантическая выборка через централизованный runtime | Маршрутизация mock PASS; live-вызова нет | BLOCKED |
| OpenAI/OpenRouter/Anthropic/local | Внешние API | Ответ через abstraction | Реальные endpoints/keys не предоставлены | BLOCKED |
| Ежедневная/недельная сводка | APScheduler + Telegram | Одно persistent-deduped сообщение | Импорт scheduler пройден, ожидание реального часа не выполнялось | NOT TESTED |
| Уведомление Telegram | Monitor + Bot API | Личное сообщение | Совпадение/cooldown unit PASS, доставка BLOCKED |
| Перезапуск и сохранность | Docker/MySQL volume | История сохраняется | Docker недоступен | BLOCKED |
| Импорт JSON export | Авторизованный API + реальный export | История импортируется | Реальный export не предоставлен | NOT TESTED |
| Удаление истории | Авторизованный API/MySQL | Только admin, производные факты удалены | Проверено кодом, end-to-end не запускалось | NOT TESTED |
| Недоступный AI API | Unit/fallback code path | Локальный поиск/расписание работают | Unit без ключа прошёл | PASS |
| Prompt injection | Разделение prompt/data и access tests | Сообщение не меняет system policy | Реальный adversarial LLM вызов не выполнен | NOT TESTED |
| Параллельные запросы | Нагрузочный тест | Нет потерь/утечек | Не выполнялся | NOT TESTED |

## Ограничения и диагностика

1. Фактически подтверждены unit-поведение хранения/поиска/изоляции/monitor cooldown, Python imports, FastAPI health и frontend build.
2. Реальная доставка Telegram, права Bot API, MySQL в контейнере и ответы внешних AI провайдеров не подтверждены. Для завершения используйте сценарий из `USER_TESTING_GUIDE.md`.
3. Telegram Bot API не предоставляет произвольную старую историю и обычно не присылает событие удаления обычного сообщения. Реализован JSON import; удаление обрабатывается только там, где update фактически доступен.
4. Встроенный APScheduler рассчитан на один bot-процесс. Для нескольких replicas нужен отдельный worker/распределённая блокировка.
5. Для Polza настроен `baai/bge-m3`; при недоступности embeddings поиск использует полнотекстовый/лексический fallback.
6. Frontend обновлён до Vite 7.3.8 и требует Node.js 20.19+; Dockerfile закреплён на `node:20.19-bookworm-slim`.
7. 42 Python warnings связаны с переходом Python 3.13 от naive UTC datetimes. Проект заявляет Python 3.12; это не провал теста, но будущая миграция на timezone-aware UTC желательна.

## Дополнительные испытания Polza.ai и маршрутизации

| Проверка | Тип | Результат | Статус |
|---|---|---|---|
| Flash для background_analysis | unit, без API | Router выбрал `deepseek/deepseek-v4-flash` даже в quality | PASS |
| Flash для economy | unit, provider mock | Фактическое поле `model` mock-запроса — Flash | PASS |
| Pro для complex RAG в auto | unit | Router выбрал `deepseek/deepseek-v4-pro` | PASS |
| Pro для quality user request | unit | Router выбрал Pro | PASS |
| Пакет из двух сообщений | unit, AI mock | Один JSON-анализ + одно batch embedding обращение, обе записи processed | PASS |
| OpenAI tool-calling contract | unit, HTTP mock | `/chat/completions`, tools, required, `parallel_tool_calls=false`, аргументы/usage разобраны | PASS |
| HTTP 402 | unit, provider mock | Один вызов, error log, persistent `insufficient_balance`, без retry | PASS |
| Журнал расходов | unit | Модель, operation, tokens, provider cost и status сохранены; prompts отсутствуют | PASS |
| Миграция Polza v2 | локальная интеграция, файловый SQLite | `/health` 200; AI settings 200/auto/configured=false/queue=0 | PASS |
| Mini App AI settings | production build | Vite собрал режимы, модели, очередь, usage и внешний AI toggle | PASS |
| Реальный Flash до исправления | CSV/JSON Polza пользователя | 50 completed, 21 failed; 23 186 токенов | PASS (evidence) |
| Реальный Pro до исправления | CSV Polza пользователя | 1 completed, 1 failed; 1 298 токенов | PASS (evidence) |
| Реальная стоимость Polza | CSV кабинета | 1,26311889 ₽ суммарно за 92 вызова | PASS (evidence) |
| Реальный tool call DeepSeek до исправления | Три JSON generation logs | `BAD_GATEWAY` при `toolChoice=required` подтверждён | FAIL |
| Реальный Polza после исправления | Повторный live-тест | Платные запросы без разрешения не выполнялись | NOT TESTED |

Официальный каталог на 22.11.2026 подтверждает ID: Flash — `deepseek/deepseek-v4-flash`, Pro — `deepseek/deepseek-v4-pro`, embedding — `baai/bge-m3`. Каталожные цены на момент аудита: Flash 1,72/3,44 ₽ за 1M входных/выходных токенов; Pro 78/156 ₽; BGE-M3 1,18 ₽ за 1M входных токенов. Цены меняются, перед live-тестом необходимо проверить кабинет Polza.

Приложенные пользователем реальные журналы подтвердили 22 failed-вызова из 92 и конкретный дефект `toolChoice=required`; он исправлен и покрыт регрессиями. Итог локально доступных проверок: PASS. Полная готовность production/live-интеграций остаётся BLOCKED до запуска Docker Desktop и повторной ручной проверки Telegram/Polza после пересборки.
