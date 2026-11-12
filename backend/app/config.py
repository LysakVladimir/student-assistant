from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень проекта (при локальном запуске: backend/app/config.py -> ../..)
ROOT_DIR = Path(__file__).resolve().parents[2]
# Один и тот же файл SQLite для backend и бота, независимо от того, из какой папки запущены процессы.
DEFAULT_SQLITE_URL = f"sqlite:///{(ROOT_DIR / 'data' / 'studypilot.db').as_posix()}"

class Settings(BaseSettings):
    telegram_bot_token: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    app_secret: str = "change-me"
    database_url: str = DEFAULT_SQLITE_URL
    dev_auth: bool = True
    default_timezone: str = "Europe/Moscow"
    # Любая дата внутри НЕЧЁТНОЙ недели (YYYY-MM-DD). Если пусто — считаем от 1 сентября.
    odd_week_reference: str = ""

    model_config = SettingsConfigDict(env_file=(str(ROOT_DIR / ".env"), ".env", "../.env"), extra="ignore")

settings = Settings()
