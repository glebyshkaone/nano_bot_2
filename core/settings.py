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
    "aspect_ratio": "match_input_image",
    "output_format": "jpg",
    "resolution": "2K",
    "safety_filter_level": "block_only_high",
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

    lines.append("\nОтправь текстовый промт — я сгенерирую картинку.")
    return "\n".join(lines)


# ---------------------------------------------------------
# DYNAMIC MENU FOR SETTINGS
# ---------------------------------------------------------

def build_settings_keyboard(settings: Dict) -> InlineKeyboardMarkup:
    model_key = settings["model"]

    keyboard = []

    # ------------------ MODEL SWITCHER ------------------
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

    # ------------------ MODEL-SPECIFIC SETTINGS ---------
    schema = MODEL_SETTINGS_SCHEMA.get(model_key, [])
    for field in schema:
        key = field["key"]
        options = field["options"]
        per_row = field.get("per_row", 3)

        row = []
        for opt in options:
            prefix = "✅ " if settings.get(key) == opt else ""
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

    # ------------------ RESET ---------------------------
    keyboard.append(
        [InlineKeyboardButton("🔁 Сбросить", callback_data="reset|settings|default")]
    )

    return InlineKeyboardMarkup(keyboard)
