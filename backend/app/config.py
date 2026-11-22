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
    ai_provider: str = "gemini"
    ai_api_key: str = ""
    ai_base_url: str = ""
    ai_model: str = ""
    ai_analysis_model: str = ""
    ai_embedding_model: str = "text-embedding-004"
    polza_api_key: str = ""
    polza_base_url: str = "https://polza.ai/api/v1"
    ai_background_model: str = "deepseek/deepseek-v4-flash"
    ai_primary_model: str = "deepseek/deepseek-v4-pro"
    ai_default_mode: str = "auto"
    ai_enabled: bool = True
    ai_background_enabled: bool = True
    ai_batch_size: int = 20
    ai_batch_max_wait_seconds: int = 90
    ai_context_char_limit: int = 30000
    ai_user_monthly_token_limit: int = 250000
    ai_background_monthly_token_limit: int = 500000
    ai_monthly_cost_limit_rub: float = 500.0
    ai_max_requests_per_minute: int = 30
    ai_monthly_request_limit: int = 10000
    ai_user_monthly_request_limit: int = 2000
    ai_background_monthly_request_limit: int = 5000
    ai_admin_telegram_id: int = 0
    ai_timeout_seconds: int = 30
    ai_max_retries: int = 2
    ai_monthly_token_limit: int = 1000000
    agent_max_tool_calls: int = 5
    max_attachment_bytes: int = 10485760
    message_retention_days: int = 365
    internal_api_token: str = ""
    app_secret: str = "change-me"
    database_url: str = DEFAULT_SQLITE_URL
    dev_auth: bool = True
    default_timezone: str = "Europe/Moscow"
    # Любая дата внутри НЕЧЁТНОЙ недели (YYYY-MM-DD). Если пусто — считаем от 1 сентября.
    odd_week_reference: str = ""

    model_config = SettingsConfigDict(env_file=(str(ROOT_DIR / ".env"), ".env", "../.env"), extra="ignore")

settings = Settings()
