from types import SimpleNamespace
from aiogram.types import Update

from bot.message_routing import is_bot_addressed, strip_bot_mention, telegram_plain_text


def test_username_mention_and_reply_are_detected():
    assert is_bot_addressed(text="@ai_studypilot_bot Что такое рекурсия?", entities=[], reply_user_id=None,
                            bot_id=10, username="ai_studypilot_bot")
    assert is_bot_addressed(text="Объясни проще", entities=[], reply_user_id=10,
                            bot_id=10, username="ai_studypilot_bot")
    assert strip_bot_mention("@ai_studypilot_bot Что такое рекурсия?", "ai_studypilot_bot") == "Что такое рекурсия?"


def test_text_mention_entity_is_detected_and_unrelated_text_is_not():
    entity = SimpleNamespace(type="text_mention", user=SimpleNamespace(id=10))
    assert is_bot_addressed(text="StudyPilot, ответь", entities=[entity], reply_user_id=None,
                            bot_id=10, username="ai_studypilot_bot")
    assert not is_bot_addressed(text="обычное сообщение группы", entities=[], reply_user_id=None,
                                bot_id=10, username="ai_studypilot_bot")
    assert telegram_plain_text("**Жирный** ответ") == "Жирный ответ"


def test_real_telegram_update_mention_structure():
    update = Update.model_validate({
        "update_id": 100,
        "message": {
            "message_id": 55, "date": 1795310000,
            "chat": {"id": -100123, "type": "supergroup", "title": "Учебная группа"},
            "from": {"id": 42, "is_bot": False, "first_name": "Иван"},
            "text": "@ai_studypilot_bot Что такое рекурсия?",
            "entities": [{"type": "mention", "offset": 0, "length": 18}],
        },
    })
    message = update.message
    assert message and message.chat.type == "supergroup"
    assert is_bot_addressed(text=message.text or "", entities=message.entities, reply_user_id=None,
                            bot_id=10, username="ai_studypilot_bot")
