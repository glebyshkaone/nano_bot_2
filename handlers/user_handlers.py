# handlers/user_handlers.py

from io import BytesIO
from typing import Optional, List

import httpx
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import ContextTypes

from config import NANO_PRICE, NANO_PRO_PRICE
from generation.nano import generate_nano
from generation.nano_pro import generate_nano_pro
from handlers.settings_handlers import (
    get_settings,
    format_settings_text,
    build_settings_keyboard,
)
from supabase_client.db import (
    ensure_user,
    get_balance,
    change_balance,
    log_generation,
)


# ---------- reply-клавиатура ----------
def build_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🚀 Старт"), KeyboardButton("🎛 Меню")],
            [KeyboardButton("💰 Баланс"), KeyboardButton("📜 История")],
        ],
        resize_keyboard=True,
    )


# ---------- команды ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update.effective_user)
    user_id = update.effective_user.id
    balance = await get_balance(user_id)
    settings = get_settings(context)

    text = (
        "Привет! Я *nano-bot* 🤖\n\n"
        "Я умею генерировать картинки через Replicate:\n"
        f"• 🍌 Nano Banana — {NANO_PRICE} токенов (basic)\n"
        f"• 🚀🍌 Nano Banana PRO — {NANO_PRO_PRICE} токенов (по умолчанию)\n\n"
        "🔹 Отправь текст — я сгенерирую картинку.\n"
        "🔹 Отправь фото с подписью — использую как референс.\n"
        "🔹 Если хочешь обычную nano-banana, начни промт с `basic:`.\n"
        "_Пример:_ `basic: girl in red coat, cinematic still`"
    )

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=build_reply_keyboard())
    await update.message.reply_text(
        format_settings_text(settings, balance=balance),
        reply_markup=build_settings_keyboard(settings),
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update.effective_user)
    user_id = update.effective_user.id
    balance = await get_balance(user_id)
    settings = get_settings(context)

    await update.message.reply_text(
        format_settings_text(settings, balance=balance),
        reply_markup=build_settings_keyboard(settings),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update.effective_user)
    text = (
        "🆘 *Как пользоваться nano-bot:*\n\n"
        f"• Nano Banana — {NANO_PRICE} токенов (дешевле)\n"
        f"• Nano Banana PRO — {NANO_PRO_PRICE} токенов (качественнее)\n\n"
        "1. Нажми «🎛 Меню» и выбери настройки.\n"
        "2. Отправь текстовый промт.\n"
        "3. По умолчанию используется PRO.\n"
        "4. Если хочешь basic-версию — начни промт с `basic:`.\n\n"
        "Пополнение баланса: напиши @glebyshkaone."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update.effective_user)
    user_id = update.effective_user.id
    balance = await get_balance(user_id)

    await update.message.reply_text(
        f"💰 Ваш баланс: *{balance}* токенов.\n\n"
        f"Nano Banana — {NANO_PRICE} токенов\n"
        f"Nano Banana PRO — {NANO_PRO_PRICE} токенов\n\n"
        "Чтобы пополнить, напишите @glebyshkaone.",
        parse_mode="Markdown",
    )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Историю генераций логичнее делать через отдельную функцию в supabase_client,
    # здесь оставим заглушку или простой текст.
    await update.message.reply_text("📜 История генераций будет реализована через Supabase.")


# ---------- общая функция генерации ----------
async def _run_generation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    image_refs: Optional[List[str]] = None,
) -> None:
    await ensure_user(update.effective_user)
    user_id = update.effective_user.id
    balance = await get_balance(user_id)
    settings = get_settings(context)

    # выбор модели по префиксу basic:
    raw_prompt = prompt.strip()
    lower = raw_prompt.lower()

    if lower.startswith("basic:"):
        model = "google/nano-banana"
        price = NANO_PRICE
        clean_prompt = raw_prompt[len("basic:") :].strip() or raw_prompt
        generator = generate_nano
    else:
        model = "google/nano-banana-pro"
        price = NANO_PRO_PRICE
        clean_prompt = raw_prompt
        generator = generate_nano_pro

    if balance < price:
        await update.message.reply_text(
            f"Недостаточно токенов: на балансе {balance}, нужно {price}.\n\n"
            "Чтобы пополнить, напишите @glebyshkaone."
        )
        return

    await update.message.reply_text("Генерирую изображение… ⚙️ Это займет 5–20 секунд.")

    try:
        image_url = await generator(
            clean_prompt,
            aspect_ratio=settings["aspect_ratio"],
            resolution=settings["resolution"],
            output_format=settings["output_format"],
            safety_filter_level=settings["safety_filter_level"],
            image_refs=image_refs,
        )

        if not image_url:
            await update.message.reply_text("Не удалось получить URL изображения от модели.")
            return

        # качаем картинку и отправляем как файл
        async with httpx.AsyncClient() as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            img_bytes = resp.content

        bio = BytesIO(img_bytes)
        bio.name = f"nano.{settings['output_format']}"
        bio.seek(0)

        await update.message.reply_photo(photo=bio)

        # списываем токены после успешной отправки
        new_balance = await change_balance(user_id, -price)
        await update.message.reply_text(
            f"Списано {price} токенов. Новый баланс: {new_balance}."
        )

        # логируем генерацию
        await log_generation(
            user_id=user_id,
            model=model,
            prompt=clean_prompt,
            image_url=image_url,
            tokens_spent=price,
            settings=settings,
        )

    except Exception as e:
        await update.message.reply_text(
            f"Произошла ошибка при генерации: {e}\n"
            "Если ошибка повторяется — напишите @glebyshkaone."
        )


# ---------- обработка текста ----------
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # кнопки
    if text == "🚀 Старт":
        await cmd_start(update, context)
        return
    if text == "🎛 Меню":
        await cmd_menu(update, context)
        return
    if text == "💰 Баланс":
        await cmd_balance(update, context)
        return
    if text == "📜 История":
        await cmd_history(update, context)
        return

    # команды уже отловлены, всё остальное — промт
    if text.startswith("/"):
        return

    await _run_generation(update, context, prompt=text)


# ---------- обработка фото ----------
async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.photo:
        return

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_url = file.file_path

    prompt = (update.message.caption or "").strip()
    if not prompt:
        prompt = "image-based generation"

    await _run_generation(update, context, prompt=prompt, image_refs=[image_url])

