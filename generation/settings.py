from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import TOKENS_PER_IMAGE  # базовая цена (можно не использовать напрямую)
from supabase_client.client import get_balance

# Конфиг моделей: ключ -> (название, токены)
MODEL_CONFIG = {
    "nano": {
        "key": "nano",
        "title": "Nano Banana",
        "price": 50,
    },
    "nano_pro": {
        "key": "nano_pro",
        "title": "Nano Banana PRO",
        "price": 150,
    },
}

# Настройки по умолчанию для генерации
DEFAULT_SETTINGS = {
    "model_key": "nano_pro",            # по умолчанию PRO
    "aspect_ratio": "4:3",
    "resolution": "2K",
    "output_format": "png",
    "safety_filter_level": "block_only_high",
}


def get_user_settings(context: ContextTypes.DEFAULT_TYPE) -> Dict:
    """
    Достаём/инициализируем настройки пользователя из context.user_data["settings"].
    """
    data = context.user_data
    settings = data.get("settings")
    if not isinstance(settings, dict):
        settings = {}
        data["settings"] = settings

    for k, v in DEFAULT_SETTINGS.items():
        settings.setdefault(k, v)

    # если модель вдруг неизвестна — ставим nano_pro
    if settings.get("model_key") not in MODEL_CONFIG:
        settings["model_key"] = "nano_pro"

    return settings


def _get_model_info(settings: Dict) -> Dict:
    key = settings.get("model_key", "nano_pro")
    return MODEL_CONFIG.get(key, MODEL_CONFIG["nano_pro"])


def format_settings_text(settings: Dict, balance: Optional[int] = None) -> str:
    """
    Текстовое описание текущих настроек + баланс.
    """
    model = _get_model_info(settings)
    bal_part = f"Ваш баланс: {balance} токенов\n\n" if balance is not None else ""

    return (
        bal_part
        + "Текущие настройки генерации:\n"
        f"• Модель: {model['title']} ({model['price']} токенов за изображение)\n"
        f"• Соотношение сторон: {settings['aspect_ratio']}\n"
        f"• Разрешение: {settings['resolution']}\n"
        f"• Формат: {settings['output_format']}\n"
        f"• Фильтр безопасности: {settings['safety_filter_level']}\n\n"
        "Отправь текстовый промт — я сгенерирую картинку по этим настройкам.\n"
        "Можешь также отправить фото с подписью — оно будет использовано как референс."
    )


def build_settings_keyboard(settings: Dict) -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура для выбора модели и параметров генерации.
    """
    model_key = settings.get("model_key", "nano_pro")
    ar = settings["aspect_ratio"]
    res = settings["resolution"]
    fmt = settings["output_format"]
    safety = settings["safety_filter_level"]

    def mark(current: str, value: str, label: str) -> str:
        return f"✅ {label}" if current == value else label

    def mark_model(current: str, value: str, label: str) -> str:
        return f"✅ {label}" if current == value else label

    keyboard = [
        # выбор модели
        [
            InlineKeyboardButton(
                mark_model(model_key, "nano", "Nano (50)"),
                callback_data="set|model_key|nano",
            ),
            InlineKeyboardButton(
                mark_model(model_key, "nano_pro", "Nano PRO (150)"),
                callback_data="set|model_key|nano_pro",
            ),
        ],
        # aspect ratio
        [
            InlineKeyboardButton(
                mark(ar, "1:1", "1:1"),
                callback_data="set|aspect_ratio|1:1",
            ),
            InlineKeyboardButton(
                mark(ar, "4:3", "4:3"),
                callback_data="set|aspect_ratio|4:3",
            ),
            InlineKeyboardButton(
                mark(ar, "16:9", "16:9"),
                callback_data="set|aspect_ratio|16:9",
            ),
            InlineKeyboardButton(
                mark(ar, "9:16", "9:16"),
                callback_data="set|aspect_ratio|9:16",
            ),
        ],
        # resolution
        [
            InlineKeyboardButton(
                mark(res, "1K", "1K"),
                callback_data="set|resolution|1K",
            ),
            InlineKeyboardButton(
                mark(res, "2K", "2K"),
                callback_data="set|resolution|2K",
            ),
            InlineKeyboardButton(
                mark(res, "4K", "4K"),
                callback_data="set|resolution|4K",
            ),
        ],
        # формат
        [
            InlineKeyboardButton(
                mark(fmt, "png", "png"),
                callback_data="set|output_format|png",
            ),
            InlineKeyboardButton(
                mark(fmt, "jpg", "jpg"),
                callback_data="set|output_format|jpg",
            ),
        ],
        # safety filter
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
            InlineKeyboardButton(
                "🔁 Сбросить к стандартным",
                callback_data="reset|settings|default",
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработка нажатий на инлайн-кнопки настроек.
    Callback data формата:
      - set|key|value
      - reset|settings|default
    """
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = (query.data or "").strip()
    parts = data.split("|")

    if not parts:
        return

    action = parts[0]

    # reset|settings|default
    if action == "reset":
        # просто очищаем настройки пользователя
        context.user_data.pop("settings", None)
        settings = get_user_settings(context)
        balance = await get_balance(query.from_user.id)
        await query.message.edit_text(
            "Настройки сброшены к стандартным.\n\n"
            + format_settings_text(settings, balance=balance),
            reply_markup=build_settings_keyboard(settings),
        )
        return

    # set|key|value
    if action == "set" and len(parts) == 3:
        key = parts[1]
        value = parts[2]

        settings = get_user_settings(context)

        # обновляем только известные ключи
        if key in DEFAULT_SETTINGS or key == "model_key":
            settings[key] = value

        balance = await get_balance(query.from_user.id)
        await query.message.edit_text(
            format_settings_text(settings, balance=balance),
            reply_markup=build_settings_keyboard(settings),
        )
        return
