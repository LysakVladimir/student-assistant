import asyncio, logging, os
from pathlib import Path
from datetime import date, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app_models import User, Lesson, BagRule
from plan import plan_text

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
if not TOKEN or TOKEN in ("replace_me", "your_bot_token"):
    raise RuntimeError("Задайте TELEGRAM_BOT_TOKEN в .env (токен из @BotFather)")
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
Session = sessionmaker(bind=engine)
router = Router()

@router.message(CommandStart())
async def start(message: Message):
    with Session() as db:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user:
            user = User(telegram_id=message.from_user.id, name=message.from_user.full_name or "Студент")
            db.add(user); db.commit()
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
    await message.answer("/today — план на сегодня\n/tomorrow — план на завтра\n/bag — список вещей\n/windows — окна между парами\n/route — время выхода\n/settings — настройки\nОткрой Mini App кнопкой в /start, чтобы редактировать расписание.")

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
    text = (message.text or "").lower()
    if any(k in text for k in ["план", "расписан", "завтра", "сегодня", "рюкзак", "вещи", "окно", "выйти", "опозда"]):
        await send_plan(message, "tomorrow" if "завтра" in text else "today")
    else:
        await message.answer("Я пока понимаю вопросы о плане, расписании, рюкзаке, окнах и времени выхода. Попробуйте /help или откройте Mini App.")

async def main():
    from app_models import Base
    Base.metadata.create_all(engine)
    bot = Bot(TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    me = await bot.get_me()  # здесь сразу видно, если токен недействителен/отозван (401 Unauthorized)
    log.info("Бот запущен: @%s, БД: %s", me.username, engine.url.render_as_string(hide_password=True))
    await bot.delete_webhook(drop_pending_updates=False)  # иначе polling конфликтует с установленным webhook
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
