# Архитектура StudyPilot

```text
Telegram Bot ─────┐
                  ├── MySQL
Telegram Mini App ── FastAPI ── AI Runtime/Router ── Polza.ai (OpenAI-compatible)
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
# Telegram AI-agent (2026-11-22)

Поток данных: `Telegram update → aiogram bot → internal authenticated FastAPI endpoint → MySQL → extraction/embedding → RAG/monitoring → Telegram or Mini App`.

Основные таблицы добавлены неразрушительно: `telegram_chats`, `chat_access`, `chat_messages`, `memory_facts`, `monitor_rules`, `agent_conversations`, `llm_usage`, `agent_notifications`, `schema_migrations`. `chat_access` — обязательная граница авторизации. Поиск, факты, удаление, импорт и ответы агента не принимают Telegram chat ID как доказательство доступа: сначала проверяется запись доступа текущего пользователя.

`backend/app/provider_client.py` изолирует протоколы провайдеров, а `backend/app/ai_runtime.py` централизует маршрутизацию и бюджеты. `backend/app/memory.py` отвечает за идемпотентный ingest, очередь, пакетный анализ, lexical/embedding search, ссылки, monitor cooldown и retention. Сообщения/файлы считаются недоверенными данными; их инструкции явно отделяются от system prompt.

Миграция версии `2026_11_22_telegram_ai_agent_v1` выполняется backend при запуске и только создаёт отсутствующие таблицы. Существующие таблицы и данные не удаляются. Для крупной production-схемы следующий шаг — перенести версии в Alembic, сохранив текущую запись `schema_migrations` как baseline.

Фоновые операции выполняет APScheduler внутри единственного bot-процесса: пакетный анализ persistent-очереди, сводки с persistent dedupe и retention. `analysis_queue` хранит необработанные сообщения до успешного завершения; 402/401/429 активируют persistent circuit breaker с backoff. При горизонтальном масштабировании bot следует вынести задачи в один worker или использовать распределённую блокировку.

`ai_runtime.py` — единственная точка маршрутизации платных вызовов. Фоновые операции всегда выбирают Flash, economy всегда Flash, auto выбирает Pro только для сложного RAG/tool-agent, quality использует Pro для пользовательских ответов, оставляя фон на Flash. `provider_client.py` реализует Polza/OpenAI-compatible contracts, structured JSON, tools, embeddings и конечные retry.

Технический журнал `llm_call_logs` не хранит prompts: только пользователь, провайдер, модель, операция, токены, оценка стоимости, provider cost, длительность, статус и код ошибки. `ai_provider_state` хранит блокировку после финансовой/авторизационной ошибки. `ai_user_settings` сохраняет режим после перезапуска; `chat_ai_settings` запрещает передачу конкретного чата внешнему AI.
