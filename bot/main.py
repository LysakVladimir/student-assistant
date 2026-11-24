import asyncio, base64, logging, os
from io import BytesIO
from pathlib import Path
from datetime import date, timedelta
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, ChatMemberUpdated
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app_models import User, Lesson, BagRule, TelegramChat, ChatAccess, AgentNotification
from plan import plan_text
from message_routing import is_bot_addressed, strip_bot_mention, telegram_plain_text

# При запуске без Docker читаем тот же .env из корня проекта, что и backend (в Docker переменные приходят из compose).
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("studypilot.bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
# Тот же файл SQLite, что и у backend, если DATABASE_URL не задан.
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{(ROOT_DIR / 'data' / 'studypilot.db').as_posix()}"
if DATABASE_URL.startswith("sqlite:///"):
    Path(DATABASE_URL.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
INTERNAL_TOKEN = os.getenv("INTERNAL_API_TOKEN") or os.getenv("APP_SECRET", "")
MAX_ATTACHMENT_BYTES = int(os.getenv("MAX_ATTACHMENT_BYTES", "10485760"))
AI_ADMIN_TELEGRAM_ID = int(os.getenv("AI_ADMIN_TELEGRAM_ID", "0") or 0)
if not TOKEN or TOKEN in ("replace_me", "your_bot_token"):
    raise RuntimeError("Задайте TELEGRAM_BOT_TOKEN в .env (токен из @BotFather)")
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
Session = sessionmaker(bind=engine)
router = Router()

def ensure_user(db, tg_user) -> User:
    user = db.query(User).filter_by(telegram_id=tg_user.id).first()
    if not user:
        user = User(telegram_id=tg_user.id, name=tg_user.full_name or "Студент")
        db.add(user); db.commit(); db.refresh(user)
    return user

async def backend_post(path: str, payload: dict) -> dict:
    if not INTERNAL_TOKEN or INTERNAL_TOKEN in {"change-me", "change-this-to-a-long-random-secret", "replace-with-a-long-random-value"}:
        raise RuntimeError("Задайте безопасный APP_SECRET или INTERNAL_API_TOKEN")
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(API_BASE_URL + path, headers={"X-Internal-Token": INTERNAL_TOKEN}, json=payload)
        response.raise_for_status()
        return response.json()

@router.message(CommandStart())
async def start(message: Message):
    with Session() as db:
        ensure_user(db, message.from_user)
    rows = []
    # Telegram принимает Web App кнопку только с https-адресом; с заглушкой/localhost /start падает с BUTTON_URL_INVALID.
    if WEBAPP_URL.startswith("https://") and "example" not in WEBAPP_URL and "localhost" not in WEBAPP_URL:
        rows.append([InlineKeyboardButton(text="Открыть StudyPilot", web_app=WebAppInfo(url=WEBAPP_URL))])
    else:
        log.warning("WEBAPP_URL не задан или не https — кнопка Mini App не показывается")
    rows.append([InlineKeyboardButton(text="План на сегодня", callback_data="today"),
                 InlineKeyboardButton(text="План на завтра", callback_data="tomorrow")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer("Привет! Я StudyPilot — помогу подготовиться к учебному дню.\n\nДобавь расписание и правила рюкзака в Mini App.", reply_markup=keyboard)

@router.callback_query(F.data.in_({"today", "tomorrow"}))
async def plan_callback(call: CallbackQuery):
    with Session() as db:
        user = db.query(User).filter_by(telegram_id=call.from_user.id).first()
        if not user:
            user = User(telegram_id=call.from_user.id, name=call.from_user.full_name or "Студент")
            db.add(user); db.commit()
        text = plan_text(db, user, call.data)
    await call.message.answer(text)
    await call.answer()

@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer("/today — план на сегодня\n/tomorrow — план на завтра\n/bag — список вещей\n/windows — окна между парами\n/route — время выхода\n/settings — настройки\n/ai — меню AI-агента\n/groups — подключённые группы\n\nВ группе администратор использует /ai_on, /ai_off и /ai_interactive. Открой Mini App кнопкой в /start, чтобы редактировать расписание.")

@router.message(Command("ai"))
async def ai_menu(message: Message):
    await message.answer("🤖 AI-агент\n\nДобавьте бота в группу, отключите Privacy Mode у BotFather и администратором выполните /ai_on. Затем задавайте мне в личном чате вопросы по переписке.\n\n/groups — группы\n/tasks — найденные задачи\n/monitors — правила мониторинга\n/ai_mode — текущий режим\n/ai_mode economy|auto|quality — изменить режим")

@router.message(Command("ai_mode"))
async def ai_mode_cmd(message: Message):
    if message.chat.type != "private": return
    parts = (message.text or "").split(maxsplit=1)
    payload = {"telegram_id": message.from_user.id}
    if len(parts) > 1: payload["mode"] = parts[1].strip().lower()
    try:
        result = await backend_post("/internal/agent/settings", payload)
        labels = {"economy": "экономичный", "auto": "автоматический", "quality": "качественный"}
        await message.answer(f"Режим: {labels.get(result['mode'], result['mode'])}\nПровайдер: {result['provider']}\nОсновная модель: {result['primary_model']}\nФоновая модель: {result['background_model']}\nAI: {'включён' if result['ai_enabled'] else 'выключен'}")
    except httpx.HTTPStatusError as exc:
        await message.answer("Не удалось изменить режим. Используйте: /ai_mode economy, /ai_mode auto или /ai_mode quality.")

@router.message(Command("groups"))
async def groups_cmd(message: Message):
    if message.chat.type != "private": return
    with Session() as db:
        user = ensure_user(db, message.from_user)
        rows = db.query(ChatAccess, TelegramChat).join(TelegramChat, ChatAccess.chat_id == TelegramChat.id).filter(ChatAccess.user_id == user.id, ChatAccess.enabled.is_(True)).all()
        text = "\n".join(f"• {c.title or c.telegram_chat_id}: {'анализ включён' if c.analysis_enabled else 'анализ выключен'}" for _,c in rows)
    await message.answer(text or "Подключённых групп пока нет. Добавьте бота в группу и выполните там /ai_on.")

@router.message(Command("tasks"))
async def tasks_cmd(message: Message):
    if message.chat.type != "private": return
    try:
        result = await backend_post("/internal/agent/chat", {"telegram_id": message.from_user.id, "message": "Какие задачи и поручения мне доступны в подключённых чатах?"})
        await message.answer(result["answer"][:4000])
    except Exception: await message.answer("Не удалось получить задачи. Проверьте backend.")

@router.message(Command("monitors"))
async def monitors_cmd(message: Message):
    await message.answer("Правила мониторинга создаются и отключаются в разделе «AI-агент» Mini App. Можно задать тему, чат, приоритет и защитный интервал между уведомлениями.")

async def require_admin(message: Message):
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return str(member.status) in {"administrator", "creator", "ChatMemberStatus.ADMINISTRATOR", "ChatMemberStatus.CREATOR"}

@router.message(Command("ai_on"))
async def ai_on(message: Message):
    if message.chat.type not in {"group", "supergroup"}: return await message.answer("Эта команда используется в группе.")
    if not await require_admin(message): return await message.answer("Включить анализ может только администратор группы.")
    with Session() as db:
        user = ensure_user(db, message.from_user)
        chat = db.query(TelegramChat).filter_by(telegram_chat_id=message.chat.id).first()
        if not chat:
            chat = TelegramChat(telegram_chat_id=message.chat.id, title=message.chat.title or "", chat_type=message.chat.type)
            db.add(chat); db.flush()
        chat.title, chat.bot_active, chat.analysis_enabled = message.chat.title or chat.title, True, True
        access = db.query(ChatAccess).filter_by(user_id=user.id, chat_id=chat.id).first()
        if not access: db.add(ChatAccess(user_id=user.id, chat_id=chat.id, role="administrator"))
        else: access.enabled, access.role = True, "administrator"
        db.commit()
    await message.answer("✅ Анализ включён. Бот сохраняет только сообщения, доступные ему с этого момента. Участники уведомлены об обработке. Для обычных сообщений отключите Privacy Mode в BotFather. Режим по умолчанию — пассивный.")

@router.message(Command("ai_join"))
async def ai_join(message: Message):
    if message.chat.type not in {"group", "supergroup"}: return
    with Session() as db:
        chat = db.query(TelegramChat).filter_by(telegram_chat_id=message.chat.id, analysis_enabled=True).first()
        if not chat: return await message.answer("Анализ этой группы ещё не активирован администратором.")
        user = ensure_user(db, message.from_user)
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        role = str(member.status).split(".")[-1].lower()
        access = db.query(ChatAccess).filter_by(user_id=user.id, chat_id=chat.id).first()
        if not access: db.add(ChatAccess(user_id=user.id, chat_id=chat.id, role=role))
        else: access.enabled, access.role = True, role
        db.commit()
    await message.answer("Группа добавлена в ваш список AI-агента. Теперь можно задавать вопросы о ней в личном чате с ботом.")

@router.message(Command("ai_off"))
async def ai_off(message: Message):
    if message.chat.type not in {"group", "supergroup"}: return
    if not await require_admin(message): return await message.answer("Отключить анализ может только администратор группы.")
    with Session() as db:
        chat = db.query(TelegramChat).filter_by(telegram_chat_id=message.chat.id).first()
        if chat: chat.analysis_enabled = False; db.commit()
    await message.answer("⏸ Анализ и сохранение новых сообщений отключены. Ранее сохранённые данные можно удалить в разделе AI-агента.")

@router.message(Command("ai_interactive"))
async def ai_interactive(message: Message):
    if message.chat.type not in {"group", "supergroup"}: return
    if not await require_admin(message): return await message.answer("Режим меняет только администратор группы.")
    arg = (message.text or "").split(maxsplit=1)
    enabled = len(arg) > 1 and arg[1].lower() in {"on", "вкл", "1"}
    with Session() as db:
        chat = db.query(TelegramChat).filter_by(telegram_chat_id=message.chat.id).first()
        if not chat: return await message.answer("Сначала выполните /ai_on.")
        chat.interactive_enabled = enabled; db.commit()
    await message.answer("Интерактивный режим включён." if enabled else "Интерактивный режим выключен; остаётся пассивный анализ.")

@router.my_chat_member()
async def bot_membership(update: ChatMemberUpdated):
    if update.chat.type not in {"group", "supergroup"}: return
    status = str(update.new_chat_member.status)
    active = status not in {"left", "kicked", "ChatMemberStatus.LEFT", "ChatMemberStatus.KICKED"}
    with Session() as db:
        chat = db.query(TelegramChat).filter_by(telegram_chat_id=update.chat.id).first()
        if not chat:
            chat = TelegramChat(telegram_chat_id=update.chat.id, title=update.chat.title or "", chat_type=update.chat.type)
            db.add(chat)
        chat.bot_active = active
        if not active: chat.analysis_enabled = False
        db.commit()

def attachment_info(message: Message):
    if message.voice: return "voice", message.voice.file_id, "voice.ogg", message.voice.mime_type or "audio/ogg", message.voice.file_size or 0
    if message.photo:
        p = message.photo[-1]; return "image", p.file_id, "image.jpg", "image/jpeg", p.file_size or 0
    if message.document: return "document", message.document.file_id, message.document.file_name or "document", message.document.mime_type or "application/octet-stream", message.document.file_size or 0
    return "text", "", "", "", 0

async def ingest_group_message(message: Message, *, addressed: bool = False):
    kind, file_id, file_name, mime, size = attachment_info(message)
    binary = ""
    if file_id and size <= MAX_ATTACHMENT_BYTES:
        try:
            stream = BytesIO(); await message.bot.download(file_id, destination=stream); binary = base64.b64encode(stream.getvalue()).decode()
        except Exception: log.exception("Не удалось скачать вложение %s", file_id)
    low = (message.text or message.caption or "").lower()
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "").lower().lstrip("@")
    priority = 10 if addressed or any(x in low for x in ("срочно", "важно", "перенос", "отмен", "дедлайн")) or (bot_username and f"@{bot_username}" in low) else 0
    payload = {"chat_id": message.chat.id, "message_id": message.message_id, "author_id": message.from_user.id if message.from_user else None,
               "author_name": message.from_user.full_name if message.from_user else "", "sent_at": message.date.isoformat(),
               "reply_to_message_id": message.reply_to_message.message_id if message.reply_to_message else None,
               "content": message.text or message.caption or "", "content_type": kind, "file_id": file_id, "file_name": file_name,
               "mime_type": mime, "binary_data": binary, "priority": priority}
    try:
        result = await backend_post("/internal/telegram/message", payload)
        if result.get("notifications"):
            with Session() as db:
                for item in result["notifications"]:
                    user = db.get(User, item["user_id"])
                    if user:
                        await message.bot.send_message(user.telegram_id, f"🔔 Совпало правило мониторинга:\n{item['message']}")
    except Exception: log.exception("Ошибка сохранения сообщения группы")

@router.edited_message(F.chat.type.in_({"group", "supergroup"}))
async def edited_group_message(message: Message):
    await ingest_group_message(message)

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def group_message(message: Message):
    if (message.text or "").startswith("/"): return
    me = await message.bot.get_me()
    reply_user_id = message.reply_to_message.from_user.id if message.reply_to_message and message.reply_to_message.from_user else None
    addressed = is_bot_addressed(text=message.text or message.caption or "", entities=message.entities or message.caption_entities,
                                 reply_user_id=reply_user_id, bot_id=me.id, username=me.username or "")
    await ingest_group_message(message, addressed=addressed)
    with Session() as db:
        chat = db.query(TelegramChat).filter_by(telegram_chat_id=message.chat.id).first()
        interactive = bool(chat and chat.interactive_enabled)
        chat_db_id = chat.id if chat else None
    if interactive and addressed and message.from_user:
        try:
            user_text = strip_bot_mention(message.text or message.caption or "", me.username or "")
            result = await backend_post("/internal/agent/chat", {"telegram_id": message.from_user.id, "message": user_text, "chat_ids": [chat_db_id]})
            await message.reply(telegram_plain_text(result["answer"])[:4000])
        except Exception:
            log.exception("Ошибка интерактивного агента")
            await message.reply("AI-агент временно недоступен. Сообщение сохранено для анализа.")

async def send_plan(message: Message, day: str):
    with Session() as db:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user:
            await message.answer("Сначала нажмите /start.")
            return
        await message.answer(plan_text(db, user, day))

@router.message(Command("today"))
async def today(message: Message): await send_plan(message, "today")
@router.message(Command("tomorrow"))
async def tomorrow(message: Message): await send_plan(message, "tomorrow")
@router.message(Command("bag"))
async def bag(message: Message):
    with Session() as db:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user: return await message.answer("Сначала нажмите /start.")
        text = plan_text(db, user, "today")
        await message.answer(text.split("🎒 Рюкзак:",1)[-1].split("\n\n🪟",1)[0].strip() if "🎒 Рюкзак:" in text else "Добавьте расписание.")
@router.message(Command("windows"))
async def windows(message: Message):
    with Session() as db:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user: return await message.answer("Сначала нажмите /start.")
        text = plan_text(db, user, "today")
        await message.answer(text.split("🪟 Окна:",1)[-1].split("\n\n⚠️",1)[0].strip() if "🪟 Окна:" in text else "Свободных окон нет.")
@router.message(Command("route"))
async def route(message: Message):
    with Session() as db:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user: return await message.answer("Сначала нажмите /start.")
        await message.answer("🚶 " + plan_text(db, user, "today").split("🚪 Время выхода:",1)[-1].split("\n",1)[0].strip())
@router.message(Command("settings"))
async def settings_cmd(message: Message):
    with Session() as db:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user: return await message.answer("Сначала нажмите /start.")
        await message.answer(f"Путь: {user.travel_minutes} мин.\nСборы: {user.prep_minutes} мин.\nЗапас: {user.buffer_minutes} мин.\nГород/адрес: {user.home_address or 'не задан'}\nИзменить настройки можно в Mini App.")

@router.message()
async def natural_language(message: Message):
    if message.chat.type != "private": return
    try:
        result = await backend_post("/internal/agent/chat", {"telegram_id": message.from_user.id, "message": message.text or ""})
        answer = result["answer"]
        links = [s.get("link") for s in result.get("sources", []) if s.get("link")]
        if links: answer += "\n\nИсточники:\n" + "\n".join(dict.fromkeys(links[:5]))
        await message.answer(telegram_plain_text(answer)[:4000])
    except Exception:
        log.exception("Ошибка AI-агента")
        await message.answer("AI-агент временно недоступен. Проверьте backend и настройку APP_SECRET; команды расписания продолжают работать.")

async def send_due_digests(bot: Bot):
    now = datetime.now()
    with Session() as db:
        rows = db.query(ChatAccess, User, TelegramChat).join(User, ChatAccess.user_id == User.id).join(TelegramChat, ChatAccess.chat_id == TelegramChat.id).filter(ChatAccess.enabled.is_(True), TelegramChat.analysis_enabled.is_(True), ChatAccess.digest_hour == now.hour, ChatAccess.digest_mode.in_(["daily", "weekly"])).all()
        due = [(a,u,c) for a,u,c in rows if a.digest_mode == "daily" or now.weekday() == 0]
    for access, user, chat in due:
        period = now.strftime("%Y-%m-%d") if access.digest_mode == "daily" else now.strftime("%G-W%V")
        key = f"digest:{access.id}:{period}"
        with Session() as db:
            if db.query(AgentNotification).filter_by(dedupe_key=key).first(): continue
            note = AgentNotification(user_id=user.id, dedupe_key=key, kind="digest")
            db.add(note)
            try: db.commit()
            except Exception: db.rollback(); continue
        try:
            prompt = "Сделай краткую ежедневную сводку важных событий, решений, задач и открытых вопросов." if access.digest_mode == "daily" else "Сделай недельную сводку важных событий, решений, задач и открытых вопросов."
            result = await backend_post("/internal/agent/chat", {"telegram_id": user.telegram_id, "message": prompt, "chat_ids": [chat.id], "detail": "brief"})
            await bot.send_message(user.telegram_id, f"🗞 {chat.title}\n\n{result['answer'][:3800]}")
            with Session() as db:
                note = db.query(AgentNotification).filter_by(dedupe_key=key).first()
                if note: note.content, note.sent_at = result["answer"][:4000], datetime.utcnow(); db.commit()
        except Exception: log.exception("Не удалось отправить сводку %s", key)

async def run_maintenance():
    try: await backend_post("/internal/maintenance", {})
    except Exception: log.exception("Ошибка очистки данных по сроку хранения")

async def run_analysis(bot: Bot):
    try:
        result = await backend_post("/internal/analysis/run", {})
        error = result.get("error", "")
        if error in {"InsufficientBalance", "AuthenticationError", "AIBudgetExceeded"} and AI_ADMIN_TELEGRAM_ID:
            key = f"ai-error:{error}:{datetime.now().strftime('%Y-%m-%d-%H')}"
            with Session() as db:
                admin = db.query(User).filter_by(telegram_id=AI_ADMIN_TELEGRAM_ID).first()
                if admin and not db.query(AgentNotification).filter_by(dedupe_key=key).first():
                    db.add(AgentNotification(user_id=admin.id, dedupe_key=key, kind="ai_error", content=error)); db.commit()
                    await bot.send_message(AI_ADMIN_TELEGRAM_ID, "⚠️ Платный AI временно остановлен: исчерпан внешний/внутренний лимит, баланс или ключ недействителен. Сообщения продолжают сохраняться и остаются в очереди.")
    except Exception: log.exception("Ошибка пакетного анализа")

async def main():
    from app_models import Base
    Base.metadata.create_all(engine)
    bot = Bot(TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    me = await bot.get_me()  # здесь сразу видно, если токен недействителен/отозван (401 Unauthorized)
    log.info("Бот запущен: @%s, БД: %s", me.username, engine.url.render_as_string(hide_password=True))
    await bot.delete_webhook(drop_pending_updates=False)  # иначе polling конфликтует с установленным webhook
    scheduler = AsyncIOScheduler(timezone=os.getenv("DEFAULT_TIMEZONE", "Europe/Moscow"))
    scheduler.add_job(send_due_digests, "cron", minute=5, args=[bot], id="agent_digests", max_instances=1, coalesce=True)
    scheduler.add_job(run_analysis, "interval", seconds=max(30, int(os.getenv("AI_BATCH_MAX_WAIT_SECONDS", "90"))), args=[bot], id="agent_batch_analysis", max_instances=1, coalesce=True)
    scheduler.add_job(run_maintenance, "cron", hour=3, minute=20, id="agent_retention", max_instances=1, coalesce=True)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
