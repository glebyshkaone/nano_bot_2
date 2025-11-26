from typing import Dict, Optional
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from config import MODEL_INFO
from core.balance import get_generation_cost_tokens


# ----------------------------------------------------
# НАСТРОЙКИ ПО УМОЛЧАНИЮ
# ----------------------------------------------------

DEFAULT_SETTINGS = {
    "model": "banana",
    "aspect_ratio": "match_input_image",
    "output_format": "jpg",
    "resolution": "2K",
    "safety_filter_level": "block_only_high",
}


# ----------------------------------------------------
# СПЕЦИФИКАЦИИ МЕНЮ ДЛЯ МОДЕЛЕЙ
# ----------------------------------------------------

BANANA_SETTINGS = {
    "aspect_ratio": [
        "match_input_image","1:1","2:3","3:2","3:4","4:3","4:5","5:4","9:16","16:9","21:9"
    ],
    "output_format": ["jpg", "png"],
}

BANANA_PRO_SETTINGS = {
    "resolution": ["1K", "2K", "4K"],
    "aspect_ratio": [
        "match_input_image","1:1","2:3","3:2","3:4","4:3","4:5","5:4","9:16","16:9","21:9"
    ],
    "output_format": ["jpg", "png"],
    "safety_filter_level": [
        "block_low_and_above",
        "block_medium_and_above",
        "block_only_high"
    ],
}


# ----------------------------------------------------
# ЛОГИКА ПОЛУЧЕНИЯ / ОБНОВЛЕНИЯ НАСТРОЕК
# ----------------------------------------------------

def get_user_settings(context: ContextTypes.DEFAULT_TYPE) -> Dict:
    data = context.user_data
    for k, v in DEFAULT_SETTINGS.items():
        data.setdefault(k, v)
    return data


# ----------------------------------------------------
# ОПИСАНИЕ ТЕКУЩИХ НАСТРОЕК (текст)
# ----------------------------------------------------

def format_settings_text(settings: Dict, balance: Optional[int] = None) -> str:
    model = settings["model"]
    cost = get_generation_cost_tokens(settings)
    res = settings.get("resolution")

    bal = f"Ваш баланс: {balance} токенов\n\n" if balance is not None else ""

    txt = f"{bal}"
    txt += f"Модель: {MODEL_INFO[model]['label']} ({cost} токенов)\n"

    if model == "banana_pro":
        txt += f"Разрешение: {settings['resolution']}\n"

    txt += f"Аспект: {settings['aspect_ratio']}\n"
    txt += f"Формат: {settings['output_format']}\n"

    if model == "banana_pro":
        txt += f"Фильтр: {settings['safety_filter_level']}\n"

    txt += "\nОтправь промт — я сгенерирую картинку."

    return txt


# ----------------------------------------------------
# ДИНАМИЧЕСКОЕ МЕНЮ НАСТРОЕК
# ----------------------------------------------------

def build_settings_keyboard(settings: Dict) -> InlineKeyboardMarkup:
    model = settings["model"]

    keyboard = []

    # ————— Выбор модели
    keyboard.append([
        InlineKeyboardButton(
            ("✅ " if model == "banana" else "") + "🍌 Banana",
            callback_data="set|model|banana"
        ),
        InlineKeyboardButton(
            ("✅ " if model == "banana_pro" else "") + "💎 Banana PRO",
            callback_data="set|model|banana_pro"
        ),
    ])

    # ————— Параметры nano-banana
    if model == "banana":
        # aspect ratio
        row = []
        for ar in BANANA_SETTINGS["aspect_ratio"]:
            row.append(
                InlineKeyboardButton(
                    ("✅ " if settings["aspect_ratio"] == ar else "") + ar,
                    callback_data=f"set|aspect_ratio|{ar}"
                )
            )
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        # output_format
        keyboard.append([
            InlineKeyboardButton(
                ("✅ " if settings["output_format"] == fmt else "") + fmt,
                callback_data=f"set|output_format|{fmt}"
            )
            for fmt in BANANA_SETTINGS["output_format"]
        ])

    # ————— Параметры nano-banana-pro
    if model == "banana_pro":

        # resolution
        keyboard.append([
            InlineKeyboardButton(
                ("✅ " if settings["resolution"] == r else "") + r,
                callback_data=f"set|resolution|{r}"
            ) for r in BANANA_PRO_SETTINGS["resolution"]
        ])

        # aspect ratio
        row = []
        for ar in BANANA_PRO_SETTINGS["aspect_ratio"]:
            row.append(
                InlineKeyboardButton(
                    ("✅ " if settings["aspect_ratio"] == ar else "") + ar,
                    callback_data=f"set|aspect_ratio|{ar}"
                )
            )
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        # output_format
        keyboard.append([
            InlineKeyboardButton(
                ("✅ " if settings["output_format"] == fmt else "") + fmt,
                callback_data=f"set|output_format|{fmt}"
            )
            for fmt in BANANA_PRO_SETTINGS["output_format"]
        ])

        # safety
        keyboard.append([
            InlineKeyboardButton(
                ("✅ " if settings["safety_filter_level"] == fl else "") + fl,
                callback_data=f"set|safety_filter_level|{fl}"
            )
            for fl in BANANA_PRO_SETTINGS["safety_filter_level"]
        ])

    # ————— Reset
    keyboard.append([
        InlineKeyboardButton("🔁 Сбросить", callback_data="reset|settings|default")
    ])

    return InlineKeyboardMarkup(keyboard)
