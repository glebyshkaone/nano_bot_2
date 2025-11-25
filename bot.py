import os
import logging
from io import BytesIO

import httpx
import replicate
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ----------------------------------------
# Логирование
# ----------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

logger.info("Starting nano-bot (UI + replicate.run)")

# ----------------------------------------
# Переменные окружения
# ----------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set")

if not REPLICATE_API_TOKEN:
    raise ValueError("REPLICATE_API_TOKEN not set")

# Логируем маскированный токен Replicate, чтобы проверить, что Railway реально подхватил нужный
logger.info(
    "REPLICATE_API_TOKEN prefix: %s..., length: %s",
    REPLICATE_API_TOKEN[:8],
    len(REPLICATE_API_TOKEN),
)

# Клиент Replicate
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ----------------------------------------
# Настройки по умолчанию
# ----------------------------------------
DEFAULT_SETTINGS = {
    "aspect_ratio": "4:3",
    "resolution": "2K",
    "output_format": "png",
    "safety_filter_level": "block_only_high",
}


def get_user_settings(context: ContextTypes.DEFAULT_TYPE) -> dict:
    data = context.user_data
    for k, v in DEFAULT_SETTINGS.items():
        data.setdefault(k, v)
    return data


def format_settings_text(settings: dict) -> str:
    return (
        "Текущие настройки генерации:\n"
        f"• Соотношение сторон: {settings['aspect_ratio']}\n"
        f"• Разрешение: {settings['resolution']}\n"
        f"• Формат: {settings['output_format']}\n"
        f"• Фильтр безопасности: {settings['safety_filter_level']}\n\n"
        "Отправь текстовый промт — я сгенерирую картинку по этим настройкам."
    )


def build_settings_keyboard(settings: dict) -> InlineKeyboardMarkup:
    ar = settings["aspect_ratio"]
    res = settings["resolution"]
    fmt = settings["output_format"]
    safety = settings["safety_filter_level"]

    def mark(current: str, value: str, label: str) -> str:
        return f"✅ {label}" if current == value else label

    keyboard = [
        # Aspect ratio
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
        # Resolution
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
        # Output format
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
        # Safety filter
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
        # Reset
        [
            InlineKeyboardButton(
                "🔁 Сбросить к стандартным",
                callback_data="reset|settings|default",
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ----------------------------------------
# Хендлеры команд
# ----------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_user_settings(context)
    text = (
        "Привет! Я nano-bot 🤖\n\n"
        "Отправь мне текстовый промт — я сгенерирую картинку через "
        "google/nano-banana-pro на Replicate.\n\n"
        "Нажми «🎛 Настройки генерации», чтобы поменять параметры."
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎛 Настройки генерации",
                    callback_data="open|settings",
                )
            ],
            [
                InlineKeyboardButton(
                    "ℹ Помощь",
                    callback_data="open|help",
                )
            ],
        ]
    )
    await update.message.reply_text(text, reply_markup=keyboard)
    await update.message.reply_text(format_settings_text(settings))


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_user_settings(context)
    await update.message.reply_text(
        format_settings_text(settings),
        reply_markup=build_settings_keyboard(settings),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Как пользоваться ботом:\n\n"
        "1. Нажми /menu или кнопку «🎛 Настройки генерации».\n"
        "2. Выбери соотношение сторон, разрешение, формат и уровень фильтра.\n"
        "3. Отправь текстовый промт (на русском или английском).\n"
        "4. Я верну сгенерированное изображение.\n\n"
        "Сейчас это MVP: одна модель (google/nano-banana-pro) и один шаг генерации."
    )
    await update.message.reply_text(text)


# ----------------------------------------
# CallbackQuery (кнопки)
# ----------------------------------------
async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data or ""
    parts = data.split("|")

    if len(parts) < 2:
        return

    action = parts[0]

    if action == "open":
        target = parts[1]
        if target == "settings":
            settings = get_user_settings(context)
            await query.message.edit_text(
                format_settings_text(settings),
                reply_markup=build_settings_keyboard(settings),
            )
        elif target == "help":
            await query.message.edit_text(
                "Это nano-bot на базе google/nano-banana-pro.\n\n"
                "Используй /menu, чтобы настроить генерацию, и просто отправляй промты.",
            )
        return

    if action == "reset":
        context.user_data.clear()
        settings = get_user_settings(context)
        await query.message.edit_text(
            "Настройки сброшены к стандартным.\n\n"
            + format_settings_text(settings),
            reply_markup=build_settings_keyboard(settings),
        )
        return

    if action == "set" and len(parts) == 3:
        key = parts[1]
        value = parts[2]
        settings = get_user_settings(context)
        if key in settings:
            settings[key] = value

        await query.message.edit_text(
            format_settings_text(settings),
            reply_markup=build_settings_keyboard(settings),
        )
        return


# ----------------------------------------
# Основной хендлер промта
# ----------------------------------------
async def handle_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    prompt = update.message.text.strip()
    if prompt.startswith("/"):
        return

    if not prompt:
        await update.message.reply_text("Отправь текстовый промт 🙏")
        return

    settings = get_user_settings(context)
    logger.info("Prompt: %s", prompt)
    logger.info("Settings: %s", settings)

    await update.message.reply_text("Генерирую картинку, подожди 5–20 секунд… ⚙️")

    try:
        input_payload = {
            "prompt": prompt,
            "aspect_ratio": settings["aspect_ratio"],
            "resolution": settings["resolution"],
            "output_format": settings["output_format"],
            "safety_filter_level": settings["safety_filter_level"],
        }

        output = replicate.run(
            "google/nano-banana-pro",
            input=input_payload,
            client=replicate_client,
        )

        logger.info("Raw output from replicate.run: %r (type=%s)", output, type(output))

        image_url = None
        if isinstance(output, list) and output:
            image_url = output[0]
        elif isinstance(output, str):
            image_url = output
        elif hasattr(output, "url"):
            val = output.url
            image_url = val() if callable(val) else val

        if not image_url:
            await update.message.reply_text(
                f"Не удалось получить URL изображения из ответа модели: {output!r}"
            )
            return

        async with httpx.AsyncClient() as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            img_bytes = resp.content

        bio = BytesIO(img_bytes)
        bio.name = f"nano-banana.{settings['output_format']}"
        bio.seek(0)

        await update.message.reply_photo(photo=bio)
        logger.info("Image successfully sent to user")

    except Exception as e:
        logger.exception("Ошибка при генерации/отправке")
        await update.message.reply_text(
            f"Произошла ошибка при генерации: {e}\n"
            "Проверь токен Replicate в Railway и попробуй ещё раз."
        )


# ----------------------------------------
# Точка входа
# ----------------------------------------
def main() -> None:
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(settings_callback))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt)
    )

    application.run_polling()


if __name__ == "__main__":
    main()
