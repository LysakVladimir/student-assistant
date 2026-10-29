import hashlib, hmac, json, time
from urllib.parse import parse_qsl
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import User

def validate_init_data(init_data: str, max_age_seconds: int = 86400) -> dict:
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured")
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise ValueError("Missing Telegram initData hash")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise ValueError("Invalid Telegram initData signature")
    auth_date = int(parsed.get("auth_date", "0"))
    if abs(int(time.time()) - auth_date) > max_age_seconds:
        raise ValueError("Telegram initData expired")
    user = json.loads(parsed.get("user", "{}"))
    if not user.get("id"):
        raise ValueError("Telegram user ID missing")
    return user

def current_user(
    x_telegram_init_data: str | None = Header(default=None),
    x_dev_telegram_id: int | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    telegram_id = None
    name = "Студент"
    if x_telegram_init_data:
        try:
            tg_user = validate_init_data(x_telegram_init_data)
            telegram_id = int(tg_user["id"])
            name = " ".join(filter(None, [tg_user.get("first_name"), tg_user.get("last_name")])) or name
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"Telegram auth failed: {exc}")
    elif settings.dev_auth and x_dev_telegram_id:
        telegram_id = x_dev_telegram_id
    else:
        raise HTTPException(status_code=401, detail="Откройте Mini App из Telegram")
    user = db.query(User).filter_by(telegram_id=telegram_id).first()
    if not user:
        user = User(telegram_id=telegram_id, name=name, timezone=settings.default_timezone)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
