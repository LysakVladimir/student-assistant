from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    telegram_bot_token: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    app_secret: str = "change-me"
    database_url: str = "sqlite:///./studypilot.db"
    dev_auth: bool = True
    default_timezone: str = "Europe/Moscow"

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

settings = Settings()
