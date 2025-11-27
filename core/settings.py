from typing import Dict, Optional
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from config import MODEL_INFO, MODEL_SETTINGS_SCHEMA
from core.balance import get_generation_cost_tokens


# ---------------------------------------------------------
# DEFAULT SETTINGS
# ---------------------------------------------------------

DEFAULT_SETTINGS = {
    "model": "banana",

    # общие / banana / banana_pro
    "aspect_ratio": "match_input_image",
    "output_format": "jpg",
    "resolution": "2K",
    "safety_filter_level": "block_only_high",

    # flux defaults
    "raw": "false",
    "seed": "off",                 # строка "off" или число в виде строки
    "safety_tolerance": "2",       # "1"–"6"
    "image_prompt_strength": "0.1" # "0.0"–"1.0"
}


def get_user_settings(context: ContextTypes.DEFAULT_TYPE) -> Dict:
    data = context.user_data
    for k, v in DEFAULT_SETTINGS.items():
        data.setdefault(k, v)
    return data


# ---------------------------------------------------------
# TEXT DESCRIPTION
# ---------------------------------------------------------

def format_settings_text(settings: Dict, balance: Optional[int] = None) -> str:
    model_key = settings["model"]
    model = MODEL_INFO[model_key]
    cost = get_generation_cost_tokens(settings)

    lines = []

    if balance is not None:
        lines.append(f"Ваш баланс: {balance} токенов\n")

    lines.append(f"Модель: {model['emoji']} {model['label']} ({cost} токенов)")

    schema = MODEL_SETTINGS_SCHEMA.get(model_key, [])
    for field in schema:
        key = field["key"]
        label = field["label"]
        value = settings.get(key)
        lines.append(f"{label}: {value}")

    # Доп.поля flux, которые задаются текстом
    if model_key == "flux_ultra":
        lines.append(f"Seed: {settings.get('seed', 'off')}")
        lines.append(f"Safety: {settings.get('safety_tolerance', '2')}")
        lines.append(f"Strength: {settings.get('image_prompt_strength', '0.1')}")

    if model_key == "remove_bg":
        lines.append("5 бесплатных удалений фона в день, затем 1₽ (1 токен).")

    lines.append("\nОтправь текстовый промт — я сгенерирую картинку.")
    lines.append("Можно отправить фото с подписью — оно станет референсом.")

    return "\n".join(lines)


# ---------------------------------------------------------
# DYNAMIC SETTINGS KEYBOARD
# ---------------------------------------------------------

def build_settings_keyboard(settings: Dict) -> InlineKeyboardMarkup:
    model_key = settings["model"]

    keyboard = []

    # ---- переключатель моделей ----
    row_models = []
    for key, info in MODEL_INFO.items():
        prefix = "✅ " if key == model_key else ""
        row_models.append(
            InlineKeyboardButton(
                f"{prefix}{info['emoji']} {info['label']}",
                callback_data=f"set|model|{key}",
            )
        )
    keyboard.append(row_models)

    # ---- поля текущей модели (по схеме) ----
    schema = MODEL_SETTINGS_SCHEMA.get(model_key, [])
    for field in schema:
        key = field["key"]
        options = field["options"]
        per_row = field.get("per_row", 3)

        row = []
        for opt in options:
            prefix = "✅ " if str(settings.get(key)) == str(opt) else ""
            row.append(
                InlineKeyboardButton(
                    f"{prefix}{opt}",
                    callback_data=f"set|{key}|{opt}",
                )
            )
            if len(row) >= per_row:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

    # ---- доп.элементы интерфейса для FLUX ----
    if model_key == "flux_ultra":
        keyboard.append([
            InlineKeyboardButton(
                f"Seed: {settings.get('seed', 'off')}",
                callback_data="input|seed",
            ),
            InlineKeyboardButton(
                f"Safety: {settings.get('safety_tolerance', '2')}",
                callback_data="input|safety_tolerance",
            ),
        ])
        keyboard.append([
            InlineKeyboardButton(
                f"Strength: {settings.get('image_prompt_strength', '0.1')}",
                callback_data="input|image_prompt_strength",
            ),
        ])

    # ---- reset ----
    keyboard.append(
        [InlineKeyboardButton("🔁 Сбросить", callback_data="reset|settings|default")]
    )

    return InlineKeyboardMarkup(keyboard)
