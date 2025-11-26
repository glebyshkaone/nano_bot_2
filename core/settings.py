from typing import Dict, Optional
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from config import MODEL_INFO


# ----------------------------------------
# Настройки по умолчанию
# ----------------------------------------
DEFAULT_SETTINGS = {
    "model": "banana",           # default модель
    "aspect_ratio": "4:3",
    "resolution": "2K",
    "output_format": "png",
    "safety_filter_level": "block_only_high",
}


def get_user_settings(context: ContextTypes.DEFAULT_TYPE) -> Dict:
    data = context.user_data
    for k, v in DEFAULT_SETTINGS.items():
        data.setdefault(k, v)
    return data


def format_settings_text(settings: Dict, balance: Optional[int] = None) -> str:
    model_key = settings["model"]
    model = MODEL_INFO[model_key]

    bal_part = f"Ваш баланс: {balance} токенов\n\n" if balance is not None else ""

    return (
        bal_part
        + f"Модель: {model['label']} ({model['cost']} токенов за изображение)\n"
        f"Соотношение сторон: {settings['aspect_ratio']}\n"
        f"Разрешение: {settings['resolution']}\n"
        f"Формат: {settings['output_format']}\n"
        f"Фильтр безопасности: {settings['safety_filter_level']}\n\n"
        "Отправь текстовый промт — я сгенерирую картинку.\n"
        "Можешь отправить фото с подписью — оно будет использовано как референс."
    )


def build_settings_keyboard(settings: Dict) -> InlineKeyboardMarkup:
    model = settings["model"]
    ar = settings["aspect_ratio"]
    res = settings["resolution"]
    fmt = settings["output_format"]
    safety = settings["safety_filter_level"]

    def mark(current: str, value: str, label: str) -> str:
        return f"✅ {label}" if current == value else label

    keyboard = [

        # МОДЕЛИ
        [
            InlineKeyboardButton(
                mark(model, "banana", "🍌 Banana (50)"),
                callback_data="set|model|banana",
            ),
            InlineKeyboardButton(
                mark(model, "banana_pro", "💎 Banana PRO (150)"),
                callback_data="set|model|banana_pro",
            ),
        ],

        # АСПЕКТ РАЦИО
        [
            InlineKeyboardButton(
                mark(ar, "1:1", "1:1"),
                callback_data="set|aspect_ratio|1:1"
            ),
            InlineKeyboardButton(
                mark(ar, "4:3", "4:3"),
                callback_data="set|aspect_ratio|4:3"
            ),
            InlineKeyboardButton(
                mark(ar, "16:9", "16:9"),
                callback_data="set|aspect_ratio|16:9"
            ),
            InlineKeyboardButton(
                mark(ar, "9:16", "9:16"),
                callback_data="set|aspect_ratio|9:16"
            ),
        ],

        # РАЗРЕШЕНИЕ
        [
            InlineKeyboardButton(
                mark(res, "1K", "1K"),
                callback_data="set|resolution|1K"
            ),
            InlineKeyboardButton(
                mark(res, "2K", "2K"),
                callback_data="set|resolution|2K"
            ),
            InlineKeyboardButton(
                mark(res, "4K", "4K"),
                callback_data="set|resolution|4K"
            ),
        ],

        # ФОРМАТ
        [
            InlineKeyboardButton(
                mark(fmt, "png", "png"),
                callback_data="set|output_format|png"
            ),
            InlineKeyboardButton(
                mark(fmt, "jpg", "jpg"),
                callback_data="set|output_format|jpg"
            ),
        ],

        # SAFE FILTER
        [
            InlineKeyboardButton(
                mark(safety, "block_only_high", "safe-high"),
                callback_data="set|safety_filter_level|block_only_high"
            ),
        ],
        [
            InlineKeyboardButton(
                mark(safety, "block_medium_and_above", "medium+"),
                callback_data="set|safety_filter_level|block_medium_and_above"
            ),
            InlineKeyboardButton(
                mark(safety, "block_low_and_above", "low+"),
                callback_data="set|safety_filter_level|block_low_and_above"
            ),
        ],

        # RESET
        [
            InlineKeyboardButton(
                "🔁 Сбросить к стандартным",
                callback_data="reset|settings|default"
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)
