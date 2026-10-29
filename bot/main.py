import asyncio, os
from datetime import date, timedelta
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app_models import User, Lesson, BagRule
from plan import plan_text

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./studypilot.db")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")
if not TOKEN or TOKEN == "replace_me":
    raise RuntimeError("Задайте TELEGRAM_BOT_TOKEN в .env")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)
router = Router()

@router.message(CommandStart())
async def start(message: Message):
    with Session() as db:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user:
            user = User(telegram_id=message.from_user.id, name=message.from_user.full_name or "Студент")
            db.add(user); db.commit()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Открыть StudyPilot", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="План на сегодня", callback_data="today"),
         InlineKeyboardButton(text="План на завтра", callback_data="tomorrow")]
    ])
    await message.answer("Привет! Я StudyPilot — помогу подготовиться к учебному дню.\n\nДобавь расписание и правила рюкзака в Mini App.", reply_markup=keyboard)

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
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
