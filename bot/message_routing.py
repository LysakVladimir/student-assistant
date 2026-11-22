"""Pure helpers for Telegram message routing (kept testable without polling)."""
import re


def is_bot_addressed(*, text: str, entities, reply_user_id: int | None, bot_id: int, username: str) -> bool:
    if reply_user_id == bot_id:
        return True
    if username and f"@{username.lower()}" in (text or "").lower():
        return True
    for entity in entities or []:
        entity_type = str(getattr(entity, "type", "")).split(".")[-1].lower()
        mentioned_user = getattr(entity, "user", None)
        if entity_type == "text_mention" and mentioned_user and mentioned_user.id == bot_id:
            return True
    return False


def strip_bot_mention(text: str, username: str) -> str:
    if not username:
        return text.strip()
    return re.sub(rf"@{re.escape(username)}\b", "", text, flags=re.IGNORECASE).strip()


def telegram_plain_text(text: str) -> str:
    """Avoid displaying raw model Markdown in Telegram's plain-text mode."""
    return (text or "").replace("**", "").replace("__", "")
