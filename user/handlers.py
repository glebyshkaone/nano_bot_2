from io import BytesIO

from telegram import Update
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    Application,
    filters,
)

from config import TOKENS_PER_IMAGE
from core.registry import register_user, is_admin
from core.balance import get_balance, deduct_tokens_for_image
from core.settings import get_user_settings, format_settings_text, build_settings_keyboard
from core.supabase import fetch_generations, log_generation
from core.generators import run_nano_banana
from .keyboards import build_reply_keyboard


# ---------- Команды ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id
    settings = get_user_settings(context)
    balance = await get_balance(user_id)

    text = (
        "Привет! Я nano-bot 🤖\n\n"
        "Отправь мне текстовый промт — я сгенерирую картинку через "
        "google/nano-banana-pro на Replicate.\n\n"
        "Можешь отправить фото с подписью — я использую его как референс (image_input).\n\n"
        "Чтобы пополнить баланс, напиши @glebyshkaone."
    )

    await update.message.reply_text(text, reply_markup=build_reply_keyboard())
    await update.message.reply_text(format_settings_text(settings, balance=balance))


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id
    settings = get_user_settings(context)
    balance = await get_balance(user_id)
    await update.message.reply_text(
        format_settings_text(settings, balance=balance),
        reply_markup=build_settings_keyboard(settings),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    text = (
        "Как пользоваться ботом:\n\n"
        f"• 1 изображение = {TOKENS_PER_IMAGE} токенов.\n"
        "• Пополнить баланс можно, написав @glebyshkaone.\n\n"
        "1. Нажми /menu или кнопку «🎛 Меню».\n"
        "2. Выбери настройки генерации.\n"
        "3. Отправь текстовый промт или фото с подписью.\n"
        "4. Если хватает токенов — я сгенерирую картинку.\n\n"
        "Команды:\n"
        "/balance — посмотреть баланс\n"
        "/history — последние генерации\n"
        "/admin — админ-панель (для админов)"
    )
    await update.message.reply_text(text)


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id
    balance = await get_balance(user_id)
    await update.message.reply_text(
        f"Ваш баланс: {balance} токенов.\n\n"
        f"1 изображение = {TOKENS_PER_IMAGE} токенов.\n"
        "Чтобы пополнить баланс, напишите @glebyshkaone."
    )


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id
    gens = await fetch_generations(user_id, limit=5)

    if not gens:
        await update.message.reply_text("Пока нет сохранённой истории генераций.")
        return

    lines = ["Ваши последние генерации (до 5):", ""]
    for g in gens:
        prompt = g.get("prompt") or ""
        ts = g.get("created_at") or ""
        tokens_spent = g.get("tokens_spent") or 0
        image_url = g.get("image_url") or ""
        short_prompt = (prompt[:80] + "…") if len(prompt) > 80 else prompt
        lines.append(f"• {short_prompt}")
        lines.append(f"  Токенов: {tokens_spent} | Время: {ts}")
        if image_url:
            lines.append(f"  {image_url}")
        lines.append("")

    await update.message.reply_text("\n".join(lines))


# ---------- Генерация ----------
async def generate_with_nano_banana(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    image_urls=None,
) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id
    balance = await get_balance(user_id)

    if balance < TOKENS_PER_IMAGE:
        await update.message.reply_text(
            f"Недостаточно токенов: на балансе {balance}, нужно {TOKENS_PER_IMAGE}.\n\n"
            "Напишите @glebyshkaone, чтобы пополнить баланс."
        )
        return

    settings = get_user_settings(context)

    await update.message.reply_text("Генерирую картинку, подожди немного… ⚙️")

    try:
        image_url, img_bytes = await run_nano_banana(prompt, settings, image_urls=image_urls)

        bio = BytesIO(img_bytes)
        bio.name = f"nano-banana.{settings['output_format']}"
        bio.seek(0)

        await update.message.reply_photo(photo=bio)

        if await deduct_tokens_for_image(user_id):
            new_balance = await get_balance(user_id)
            await update.message.reply_text(
                f"Списано {TOKENS_PER_IMAGE} токенов. Новый баланс: {new_balance}."
            )
            await log_generation(
                user_id=user_id,
                prompt=prompt,
                image_url=image_url,
                settings=settings,
                tokens_spent=TOKENS_PER_IMAGE,
            )
        else:
            await update.message.reply_text(
                "Изображение сгенерировано, но не удалось списать токены — обратитесь к администратору."
            )

    except Exception as e:
        import logging
        logging.exception("Ошибка при генерации/отправке")
        await update.message.reply_text(
            f"Произошла ошибка при генерации: {e}\n"
            "Если ошибка повторяется — напишите @glebyshkaone."
        )


# ---------- Текстовый промт ----------
async def handle_text_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    prompt = update.message.text.strip()
    if prompt.startswith("/"):
        return

    if not prompt:
        await update.message.reply_text("Отправь текстовый промт 🙏")
        return

    await generate_with_nano_banana(update, context, prompt, image_urls=None)


# ---------- Фото как референс ----------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    message = update.message
    if not message or not message.photo:
        return

    photo = message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_url = file.file_path

    prompt = (message.caption or "").strip() or "image to image generation"
    await generate_with_nano_banana(update, context, prompt, image_urls=[image_url])


# ---------- Reply-кнопки + админ поиск ----------
async def handle_reply_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id

    # Режим админского поиска
    if is_admin(user_id) and context.user_data.get("admin_search_mode"):
        from core.supabase import supabase_search_users
        from admin.views import build_admin_main_keyboard

        context.user_data["admin_search_mode"] = False
        query = text.lstrip("@").strip()
        users = await supabase_search_users(query, limit=20)

        if not users:
            await update.message.reply_text(
                f"По запросу «{query}» пользователей не найдено.",
            )
            return

        total = len(users)
        lines = [
            f"Результаты поиска по «{query}» (найдено {total}):",
            "",
            "Нажми на пользователя, чтобы открыть карточку.",
        ]
        kb = build_admin_main_keyboard(users)
        await update.message.reply_text("\n".join(lines), reply_markup=kb)
        return

    # Обычные кнопки
    if text == "🚀 Старт":
        await start(update, context)
        return
    if text == "🎛 Меню":
        await menu_command(update, context)
        return
    if text == "ℹ Помощь":
        await help_command(update, context)
        return
    if text == "💰 Баланс":
        await balance_command(update, context)
        return
    if text == "📜 История":
        await history_command(update, context)
        return

    # Всё остальное — текстовый промт
    await handle_text_prompt(update, context)


# ---------- Callback настроек генерации ----------
async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    if (query.data or "").startswith("admin_"):
        return  # админ-колбэки обрабатываются в admin.handlers

    await query.answer()
    data = query.data or ""
    parts = data.split("|")
    if not parts:
        return

    from core.balance import get_balance  # чтобы не было цикличности импортов

    action = parts[0]
    if action == "reset":
        context.user_data.clear()
        settings = get_user_settings(context)
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
        settings = get_user_settings(context)
        if key in settings:
            settings[key] = value
        balance = await get_balance(query.from_user.id)
        await query.message.edit_text(
            format_settings_text(settings, balance=balance),
            reply_markup=build_settings_keyboard(settings),
        )


# ---------- Регистрация хендлеров ----------
def register_user_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("history", history_command))

    # Callback настроек генерации (после admin_callback в main.py)
    app.add_handler(CallbackQueryHandler(settings_callback))

    # Фото и текст
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_buttons)
    )
