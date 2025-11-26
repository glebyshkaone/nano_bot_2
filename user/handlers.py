from io import BytesIO
import logging

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
)
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    Application,
    filters,
)

from config import MODEL_INFO
from core.registry import register_user, is_admin
from core.balance import (
    get_balance,
    deduct_tokens,
    add_tokens,
    get_generation_cost_tokens,
)
from core.settings import get_user_settings, format_settings_text, build_settings_keyboard
from core.supabase import fetch_generations, log_generation
from core.generators import run_model
from .keyboards import build_reply_keyboard

logger = logging.getLogger(__name__)

# ---------- Константы для оплаты ----------

# Базовая экономика: 150 токенов ~ 25⭐
STARS_PER_150_TOKENS = 25
PAYLOAD_PREFIX = "buy_tokens:"
# Стандартные паки (в токенах)
TOKEN_PACKS = [500, 1000, 1500]
CUSTOM_TOKENS_KEY = "awaiting_custom_tokens"


def tokens_to_stars(tokens: int) -> int:
    """
    Переводим токены в звёзды по базовому курсу:
    150 токенов -> STARS_PER_150_TOKENS звёзд.
    """
    stars = round(tokens * STARS_PER_150_TOKENS / 150)
    return max(1, stars)


# ---------- Базовые команды ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id
    settings = get_user_settings(context)
    balance = await get_balance(user_id)

    text = (
        "Привет! Я nano-bot 🤖\n\n"
        "Отправь мне текстовый промт — я сгенерирую картинку через модели "
        "google/nano-banana / nano-banana-pro на Replicate.\n\n"
        "Можешь отправить фото с подписью — я использую его как референс (image_input).\n\n"
        "Чтобы пополнить баланс токенов через Telegram Stars, используй /buy."
    )

    if update.message:
        await update.message.reply_text(text, reply_markup=build_reply_keyboard())
        await update.message.reply_text(format_settings_text(settings, balance=balance))


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    settings = get_user_settings(context)
    balance = await get_balance(update.effective_user.id)
    await update.message.reply_text(
        format_settings_text(settings, balance=balance),
        reply_markup=build_settings_keyboard(settings),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)

    banana_cost = MODEL_INFO["banana"]["base_cost"]
    pro_base = MODEL_INFO["banana_pro"]["base_cost"]
    pro_4k = pro_base * 2

    text = (
        "Как пользоваться ботом:\n\n"
        f"• Banana — {banana_cost} токенов за изображение.\n"
        f"• Banana PRO — {pro_base} токенов за 1K/2K и {pro_4k} токенов за 4K.\n\n"
        "Пополнение токенов через Telegram Stars:\n"
        "• Стандартные паки: 500 / 1000 / 1500 токенов.\n"
        "• Можно ввести любое количество токенов вручную.\n"
        "Команда: /buy\n\n"
        "Основные команды:\n"
        "/menu — настройки генерации\n"
        "/model — выбор модели\n"
        "/balance — баланс токенов\n"
        "/history — последние генерации\n"
        "/buy — пополнить токены\n"
        "/admin — админ-панель (для админов)"
    )
    await update.message.reply_text(text)


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id
    balance = await get_balance(user_id)

    banana_cost = MODEL_INFO["banana"]["base_cost"]
    pro_base = MODEL_INFO["banana_pro"]["base_cost"]
    pro_4k = pro_base * 2

    text_lines = [
        f"Ваш баланс: {balance} токенов.\n",
        "Тарифы генерации:",
        f"• Banana — {banana_cost} токенов",
        f"• Banana PRO — {pro_base} токенов (1K/2K), {pro_4k} токенов (4K)",
        "",
        "Пополнение через Telegram Stars (/buy):",
    ]

    for t in TOKEN_PACKS:
        stars = tokens_to_stars(t)
        text_lines.append(f"• {t} токенов — {stars}⭐")

    text_lines.append(
        "• Другое количество — выбираете сами, токены пересчитаются в ⭐ по тому же курсу."
    )

    await update.message.reply_text("\n".join(text_lines))


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


# ---------- Меню выбора модели ----------

async def model_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отдельное компактное меню только для выбора модели."""
    await register_user(update.effective_user)
    settings = get_user_settings(context)
    current_model = settings["model"]

    banana_cost = MODEL_INFO["banana"]["base_cost"]
    pro_base = MODEL_INFO["banana_pro"]["base_cost"]
    pro_4k = pro_base * 2

    text = (
        "🧠 Выбор модели генерации\n\n"
        f"Текущая модель: *{MODEL_INFO[current_model]['label']}*\n\n"
        f"• 🍌 Banana — {banana_cost} токенов за изображение.\n"
        f"• 💎 Banana PRO — {pro_base} токенов (1K/2K), {pro_4k} токенов (4K).\n\n"
        "Выбери модель ниже:"
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    ("✅ " if current_model == "banana" else "") + "🍌 Banana",
                    callback_data="set|model|banana",
                ),
                InlineKeyboardButton(
                    ("✅ " if current_model == "banana_pro" else "") + "💎 Banana PRO",
                    callback_data="set|model|banana_pro",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⬅ Вернуться в меню",
                    callback_data="back|menu",
                )
            ],
        ]
    )

    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


# ---------- Генерация ----------

async def generate_with_nano_banana(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    image_urls=None,
) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id

    settings = get_user_settings(context)

    ok, cost, current_or_new = await deduct_tokens(user_id, settings)
    if not ok:
        await update.message.reply_text(
            f"Недостаточно токенов: на балансе {current_or_new}, нужно {cost}.\n\n"
            "Используйте /buy, чтобы пополнить баланс через Telegram Stars."
        )
        return

    await update.message.reply_text("Генерирую картинку, подожди немного… ⚙️")

    try:
        image_url, img_bytes = await run_model(prompt, settings, image_urls=image_urls)

        bio = BytesIO(img_bytes)
        bio.name = f"nano-banana.{settings['output_format']}"
        bio.seek(0)

        await update.message.reply_photo(photo=bio)

        new_balance = await get_balance(user_id)
        await update.message.reply_text(
            f"Списано {cost} токенов. Новый баланс: {new_balance}."
        )

        await log_generation(
            user_id=user_id,
            prompt=prompt,
            image_url=image_url,
            settings=settings,
            tokens_spent=cost,
        )

    except Exception as e:
        logger.exception("Ошибка при генерации/отправке")
        await update.message.reply_text(
            f"Произошла ошибка при генерации: {e}\n"
            "Если ошибка повторяется — напишите @glebyshkaone."
        )


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


# ---------- Покупка токенов через Stars ----------

async def buy_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Меню покупки токенов: 500 / 1000 / 1500 + своё количество."""
    await register_user(update.effective_user)

    lines = [
        "Пополнение токенов через Telegram Stars:",
        "",
        "Выберите один из стандартных пакетов или укажите своё количество.",
        "",
    ]

    for t in TOKEN_PACKS:
        stars = tokens_to_stars(t)
        lines.append(f"• {t} токенов — {stars}⭐")
    lines.append("")
    lines.append("Или нажмите «Другое количество», чтобы ввести токены вручную.")

    keyboard = [
        [
            InlineKeyboardButton("500 токенов", callback_data="buy_pack|500"),
            InlineKeyboardButton("1000 токенов", callback_data="buy_pack|1000"),
        ],
        [
            InlineKeyboardButton("1500 токенов", callback_data="buy_pack|1500"),
        ],
        [
            InlineKeyboardButton("Другое количество", callback_data="buy_custom"),
        ],
    ]

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка inline-кнопок из меню покупки."""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data or ""

    chat_id = query.message.chat_id

    # Стандартные паки
    if data.startswith("buy_pack|"):
        try:
            tokens = int(data.split("|")[1])
        except (IndexError, ValueError):
            await query.message.reply_text("Ошибка в параметрах пакета. Попробуйте ещё раз.")
            return

        stars = tokens_to_stars(tokens)

        prices = [LabeledPrice(label=f"{tokens} токенов", amount=stars)]

        payload = f"{PAYLOAD_PREFIX}{tokens}"

        await query.message.reply_text(
            f"Вы покупаете {tokens} токенов за {stars}⭐.\n"
            "Оплата пройдёт через Telegram Stars."
        )

        await context.bot.send_invoice(
            chat_id=chat_id,
            title=f"{tokens} токенов",
            description=f"Пакет {tokens} токенов для nano-bot.",
            payload=payload,
            provider_token="",  # для Telegram Stars пустая строка
            currency="XTR",
            prices=prices,
            max_tip_amount=0,
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            send_phone_number_to_provider=False,
            send_email_to_provider=False,
            is_flexible=False,
        )
        return

    # Кастомное количество
    if data == "buy_custom":
        context.user_data[CUSTOM_TOKENS_KEY] = True
        await query.message.reply_text(
            "Введите, сколько токенов вы хотите купить (целое число). "
            "Я покажу стоимость в ⭐ и предложу оплату."
        )
        return


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждаем заказ перед списанием Stars."""
    query = update.pre_checkout_query
    payload = query.invoice_payload or ""

    if not payload.startswith(PAYLOAD_PREFIX):
        await query.answer(ok=False, error_message="Неверный товар. Напишите @glebyshkaone.")
        return

    await query.answer(ok=True)


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начисляем токены после успешной оплаты Stars."""
    message = update.message
    if not message or not message.successful_payment:
        return

    payment = message.successful_payment
    payload = payment.invoice_payload or ""

    if not payload.startswith(PAYLOAD_PREFIX):
        return

    try:
        tokens_to_add = int(payload[len(PAYLOAD_PREFIX):])
    except ValueError:
        return

    user_id = update.effective_user.id
    new_balance = await add_tokens(user_id, tokens_to_add)

    await message.reply_text(
        f"Оплата прошла успешно ✅\n"
        f"Зачислено {tokens_to_add} токенов.\n"
        f"Текущий баланс: {new_balance} токенов.\n\n"
        "Теперь можно отправлять промты ✨"
    )


# ---------- Reply-кнопки + спец-режимы ----------

async def handle_reply_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id

    # Кастомный ввод токенов для покупки
    if context.user_data.get(CUSTOM_TOKENS_KEY):
        context.user_data[CUSTOM_TOKENS_KEY] = False
        try:
            tokens = int(text)
            if tokens <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "Нужно ввести положительное целое число токенов. "
                "Попробуйте снова через /buy."
            )
            return

        stars = tokens_to_stars(tokens)
        await update.message.reply_text(
            f"Вы хотите купить {tokens} токенов.\n"
            f"Стоимость: {stars}⭐.\n"
            "Сейчас пришлю счёт."
        )

        prices = [LabeledPrice(label=f"{tokens} токенов", amount=stars)]
        payload = f"{PAYLOAD_PREFIX}{tokens}"

        try:
            await context.bot.send_invoice(
                chat_id=update.effective_chat.id,
                title=f"{tokens} токенов",
                description=f"Пакет {tokens} токенов для nano-bot.",
                payload=payload,
                provider_token="",
                currency="XTR",
                prices=prices,
                max_tip_amount=0,
                need_name=False,
                need_phone_number=False,
                need_email=False,
                need_shipping_address=False,
                send_phone_number_to_provider=False,
                send_email_to_provider=False,
                is_flexible=False,
            )
        except Exception as e:
            logger.exception("Ошибка при отправке инвойса для кастомного количества токенов")
            await update.message.reply_text(
                f"Не удалось создать счёт: {e}\n"
                "Попробуйте ещё раз через /buy или напишите @glebyshkaone."
            )

        return

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
    if text == "🧠 Модель":
        await model_menu_command(update, context)
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

    data = query.data or ""

    # админ-колбэки обрабатываются в admin.handlers
    if data.startswith("admin_"):
        return

    # колбэки оплаты обрабатываются в buy_callback
    if data.startswith("buy_"):
        return

    await query.answer()

    # спец-кейс: кнопка "⬅ Вернуться в меню" из модельного меню
    if data == "back|menu":
        settings = get_user_settings(context)
        balance = await get_balance(query.from_user.id)
        await query.message.edit_text(
            format_settings_text(settings, balance=balance),
            reply_markup=build_settings_keyboard(settings),
        )
        return

    parts = data.split("|")
    if not parts:
        return

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

        # если меняли модель — даём подсказку выбрать настройки
        if key == "model":
            header = "Модель обновлена. Теперь выбери настройки для неё:\n\n"
        else:
            header = ""

        await query.message.edit_text(
            header + format_settings_text(settings, balance=balance),
            reply_markup=build_settings_keyboard(settings),
        )


# ---------- Регистрация хендлеров ----------

def register_user_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("model", model_menu_command))
    app.add_handler(CommandHandler("buy", buy_menu_command))

    # оплатные колбэки (перед settings_callback)
    app.add_handler(CallbackQueryHandler(buy_callback, pattern=r"^buy_"))

    # Callback настроек генерации
    app.add_handler(CallbackQueryHandler(settings_callback))

    # Pre-checkout + успешная оплата
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    # Фото и текст
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_buttons)
    )
