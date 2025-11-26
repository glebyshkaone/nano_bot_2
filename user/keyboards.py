from telegram import ReplyKeyboardMarkup, KeyboardButton


def build_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("🚀 Старт"), KeyboardButton("🎛 Меню")],
        [KeyboardButton("🧠 Модель"), KeyboardButton("💰 Баланс")],
        [KeyboardButton("📜 История"), KeyboardButton("ℹ Помощь")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

