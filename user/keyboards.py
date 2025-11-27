from telegram import ReplyKeyboardMarkup, KeyboardButton


def build_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("👤 Профиль"), KeyboardButton("🤖 GPTs")],
        [KeyboardButton("🖼️ Изображения"), KeyboardButton("🎬 Видео")],
        [KeyboardButton("ℹ Помощь"), KeyboardButton("📚 База знаний")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

