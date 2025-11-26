# handlers/settings_handlers.py

from typing import Dict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from supabase_client.db import get_balance


DEFAULT_SETTINGS: Dict[str, str] = {
    "aspect_ratio": "4:3",
    "resolution": "2K",
    "output_format": "png",
    "safety_filter_level": "block_only_high",
}


def get_settings(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, str]:
    """Возвращает (и инициализирует) настройки пользователя из context.user_data."""
    data = context.user_data
    for k, v in DEFAULT_SETTINGS.items():
        data.setdefault(k, v)
    return data


def format_settings_text(settings: Dict[str, str], balance: int | None = None) -> str:
    bal_part = f"Ваш баланс: {balance} токенов\n\n" if balance is not None else ""
    return (
        bal_part
        + "🎛 Текущие настройки генерации:\n"
        f"• Соотношение сторон: {settings['aspect_ratio']}\n"
        f"• Разрешение: {settings['resolution']}\n"
        f"• Формат: {settings['output_format']}\n"
        f"• Фильтр безопасности: {settings['safety_filter_level']}\n\n"
        "✏ Измени параметры кнопками ниже и отправь промт.\n"
        "📸 Можно отправить фото с подписью — оно станет референсом."
    )


def build_settings_keyboard(settings: Dict[str, str]) -> InlineKeyboardMarkup:
    ar = settings["aspect_ratio"]
    res = settings["resolution"]
    fmt = settings["output_format"]
    safety = settings["safety_filter_level"]

    def mark(current: str, value: str, label: str) -> str:
        return f"✅ {label}" if current == value else label

    keyboard = [
        # aspect_ratio
        [
            InlineKeyboardButton(mark(ar, "1:1", "1:1"), callback_data="set|aspect_ratio|1:1"),
            InlineKeyboardButton(mark(ar, "4:3", "4:3"), callback_data="set|aspect_ratio|4:3"),
            InlineKeyboardButton(mark(ar, "16:9", "16:9"), callback_data="set|aspect_ratio|16:9"),
            InlineKeyboardButton(mark(ar, "9:16", "9:16"), callback_data="set|aspect_ratio|9:16"),
        ],
        # resolution
        [
            InlineKeyboardButton(mark(res, "1K", "1K"), callback_data="set|resolution|1K"),
            InlineKeyboardButton(mark(res, "2K", "2K"), callback_data="set|resolution|2K"),
            InlineKeyboardButton(mark(res, "4K", "4K"), callback_data="set|resolution|4K"),
        ],
        # формат
        [
            InlineKeyboardButton(mark(fmt, "png", "png"), callback_data="set|output_format|png"),
            InlineKeyboardButton(mark(fmt, "jpg", "jpg"), callback_data="set|output_format|jpg"),
        ],
        # safety
        [
            InlineKeyboardButton(
                mark(safety, "block_only_high", "safe (high)"),
                callback_data="set|safety_filter_level|block_only_high",
            ),
        ],
        [
            InlineKeyboardButton(
                mark(safety, "block_medium_and_above", "medium+"),
                callback_data="set|safety_filter_level|block_medium_and_above",
            ),
            InlineKeyboardButton(
                mark(safety, "block_low_and_above", "low+"),
                callback_data="set|safety_filter_level|block_low_and_above",
            ),
        ],
        [
            InlineKeyboardButton("🔁 Сбросить", callback_data="reset|settings|default"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатий на inline-кнопки настроек (set|... / reset|...)."""
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    # admin_* коллбеки обрабатываются в admin_handlers
    if data.startswith("admin_"):
        return

    await query.answer()

    parts = data.split("|")
    action = parts[0]

    if action == "reset":
        # полный сброс user_data
        context.user_data.clear()
        settings = get_settings(context)
        balance = await get_balance(query.from_user.id)
        await query.message.edit_text(
            "Настройки сброшены к стандартным.\n\n"
            + format_settings_text(settings, balance=balance),
            reply_markup=build_settings_keyboard(settings),
        )
        return

    if action == "set" and len(parts) == 3:
        key = parts[1]
        value = parts[2]
        settings = get_settings(context)
        if key in settings:
            settings[key] = value

        balance = await get_balance(query.from_user.id)
        await query.message.edit_text(
            format_settings_text(settings, balance=balance),
            reply_markup=build_settings_keyboard(settings),
        )
        return

