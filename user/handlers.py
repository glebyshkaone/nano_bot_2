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

# 150 токенов = 25 звёзд
STARS_PER_150_TOKENS = 25
PAYLOAD_PREFIX = "buy_tokens:"
TOKEN_PACKS = [500, 1000, 1500]
CUSTOM_TOKENS_KEY = "awaiting_custom_tokens"


def tokens_to_stars(tokens: int) -> int:
    stars = round(tokens * STARS_PER_150_TOKENS / 150)
    return max(1, stars)


# ---------- Команды ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    settings = get_user_settings(context)
    balance = await get_balance(update.effective_user.id)

    text = (
        "Привет! Я nano-bot 🤖\n\n"
        "Отправь текстовый промт — я сгенерирую картинку.\n"
        "Можешь отправить фото с подписью — оно станет референсом.\n\n"
        "Пополнить токены (Telegram Stars): /buy"
    )

    await update.message.reply_text(text, reply_markup=build_reply_keyboard())
    await update.message.reply_text(format_settings_text(settings, balance=balance))


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_user_settings(context)
    balance = await get_balance(update.effective_user.id)
    await update.message.reply_text(
        format_settings_text(settings, balance=balance),
        reply_markup=build_settings_keyboard(settings),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    banana_cost = MODEL_INFO["banana"]["base_cost"]
    pro_base = MODEL_INFO["banana_pro"]["base_cost"]
    pro_4k = pro_base * 2

    text = (
        "Как пользоваться ботом:\n\n"
        f"• Banana — {banana_cost} токенов\n"
        f"• Banana PRO — {pro_base} токенов (1K/2K) / {pro_4k} токенов (4K)\n\n"
        "Пополнение токенов через Telegram Stars: /buy\n\n"
        "Команды:\n"
        "/menu — настройки\n"
        "/model — смена модели\n"
        "/balance — баланс токенов\n"
        "/history — история генераций\n"
    )
    await update.message.reply_text(text)


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    balance = await get_balance(update.effective_user.id)
    banana_cost = MODEL_INFO["banana"]["base_cost"]
    pro_base = MODEL_INFO["banana_pro"]["base_cost"]
    pro_4k = pro_base * 2

    lines = [
        f"Ваш баланс: {balance} токенов.\n",
        "Стоимость генерации:",
        f"• Banana — {banana_cost}",
        f"• Banana PRO — {pro_base} (1K/2K), {pro_4k} (4K)",
        "",
        "Пополнение (/buy):",
    ]
    for t in TOKEN_PACKS:
        lines.append(f"• {t} токенов — {tokens_to_stars(t)}⭐")

    lines.append("• Другое количество — вручную.")

    await update.message.reply_text("\n".join(lines))


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    gens = await fetch_generations(user_id, limit=5)

    if not gens:
        await update.message.reply_text("История пустая.")
        return

    lines = ["Последние генерации:\n"]
    for g in gens:
        prompt = g.get("prompt", "")
        short = prompt[:80] + ("…" if len(prompt) > 80 else "")
        lines.append(f"• {short}")
        lines.append(f"  {g.get('tokens_spent')} токенов | {g.get('created_at')}")
        url = g.get("image_url")
        if url:
            lines.append(url)
        lines.append("")

    await update.message.reply_text("\n".join(lines))


# ---------- Выбор модели ----------

async def model_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_user_settings(context)
    current = settings["model"]

    banana_cost = MODEL_INFO["banana"]["base_cost"]
    pro_base = MODEL_INFO["banana_pro"]["base_cost"]
    pro_4k = pro_base * 2

    text = (
        "🧠 Выбор модели:\n\n"
        f"• Banana — {banana_cost} токенов\n"
        f"• Banana PRO — {pro_base} / {pro_4k} (4K)\n\n"
        f"Текущая: {MODEL_INFO[current]['label']}"
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    ("✅ " if current == "banana" else "") + "🍌 Banana",
                    callback_data="set|model|banana",
                ),
                InlineKeyboardButton(
                    ("✅ " if current == "banana_pro" else "") + "💎 Banana PRO",
                    callback_data="set|model|banana_pro",
                ),
            ],
            [InlineKeyboardButton("⬅ Назад", callback_data="back|menu")],
        ]
    )

    await update.message.reply_text(text, reply_markup=kb)


# ---------- Генерация (ТОЛЬКО успешная списывает токены) ----------

async def generate_with_nano_banana(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    image_urls=None,
) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id
    settings = get_user_settings(context)

    # 1. Проверяем баланс (не списывая)
    cost = get_generation_cost_tokens(settings)
    balance = await get_balance(user_id)

    if balance < cost:
        await update.message.reply_text(
            f"Нужно {cost} токенов, у вас {balance}.\nПополните через /buy"
        )
        return

    await update.message.reply_text("Генерирую… ⚙️")

    try:
        # 2. Генерируем КАРТИНКУ
        image_url, img_bytes = await run_model(prompt, settings, image_urls=image_urls)

        # 3. Если дошли сюда — генерация успешна → списываем токены
        ok, used_cost, new_balance = await deduct_tokens(user_id, settings)
        if not ok:
            logger.error("Не удалось списать токены после успешной генерации.")
            used_cost = 0
            new_balance = await get_balance(user_id)

        # 4. Отправляем итог
        bio = BytesIO(img_bytes)
        bio.name = f"nano-banana.{settings['output_format']}"
        bio.seek(0)

        await update.message.reply_photo(photo=bio)

        if used_cost > 0:
            await update.message.reply_text(
                f"Списано {used_cost} токенов. Баланс: {new_balance}."
            )
        else:
            await update.message.reply_text(
                "Генерация успешна, но токены не списались. Сообщите @glebyshkaone."
            )

        # Лог
        await log_generation(
            user_id=user_id,
            prompt=prompt,
            image_url=image_url,
            settings=settings,
            tokens_spent=used_cost or cost,
        )

    except Exception as e:
        logger.exception("Ошибка генерации")
        await update.message.reply_text(
            f"Ошибка при генерации. Токены НЕ списаны.\n{e}"
        )


# ---------- Обработка текстовых промтов ----------

async def handle_text_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if not text or text.startswith("/"):
        return
    await generate_with_nano_banana(update, context, text, image_urls=None)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    photo = message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_url = file.file_path

    prompt = (message.caption or "").strip() or "image to image"
    await generate_with_nano_banana(update, context, prompt, image_urls=[image_url])


# ---------- Покупка токенов через Stars ----------

async def buy_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["Пополнение токенов через Telegram Stars:\n"]
    for t in TOKEN_PACKS:
        lines.append(f"• {t} токенов — {tokens_to_stars(t)}⭐")

    lines.append("\nДругое количество — вручную.")

    kb = [
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
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    await query.answer()

    # Покупка готового пакета
    if data.startswith("buy_pack|"):
        tokens = int(data.split("|")[1])
        stars = tokens_to_stars(tokens)

        payload = f"{PAYLOAD_PREFIX}{tokens}"
        prices = [LabeledPrice(label=f"{tokens} токенов", amount=stars)]

        await query.message.reply_text(
            f"Покупка {tokens} токенов за {stars}⭐"
        )

        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=f"{tokens} токенов",
            description="Пополнение токенов nano-bot.",
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=prices,
        )
        return

    # Произвольное количество
    if data == "buy_custom":
        context.user_data[CUSTOM_TOKENS_KEY] = True
        await query.message.reply_text("Введите количество токенов:")
        return


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    if not query.invoice_payload.startswith(PAYLOAD_PREFIX):
        await query.answer(ok=False, error_message="Ошибка товара.")
        return

    await query.answer(ok=True)


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    payment = update.message.successful_payment
    tokens = int(payment.invoice_payload[len(PAYLOAD_PREFIX):])

    new_balance = await add_tokens(update.effective_user.id, tokens)

    await update.message.reply_text(
        f"Успешная оплата! +{tokens} токенов.\nБаланс: {new_balance}"
    )


# ---------- Текст + кнопки ----------

async def handle_reply_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    user_id = update.effective_user.id

    # ----- кастомный ввод количества токенов -----
    if context.user_data.get(CUSTOM_TOKENS_KEY):
        context.user_data[CUSTOM_TOKENS_KEY] = False

        try:
            tokens = int(text)
        except:
            await update.message.reply_text("Введите число.")
            return

        stars = tokens_to_stars(tokens)
        payload = f"{PAYLOAD_PREFIX}{tokens}"
        prices = [LabeledPrice(label=f"{tokens} токенов", amount=stars)]

        await update.message.reply_text(f"{tokens} токенов = {stars}⭐")

        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=f"{tokens} токенов",
            description="Пополнение токенов nano-bot.",
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=prices,
        )
        return

    # -------- обычные кнопки --------
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

    # иначе → промт
    await handle_text_prompt(update, context)


# ---------- Callback настроек ----------

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    if data.startswith("buy_"):
        return

    if data == "back|menu":
        settings = get_user_settings(context)
        bal = await get_balance(query.from_user.id)
        await query.message.edit_text(
            format_settings_text(settings, balance=bal),
            reply_markup=build_settings_keyboard(settings),
        )
        return

    await query.answer()

    parts = data.split("|")
    if parts[0] == "reset":
        context.user_data.clear()
        settings = get_user_settings(context)
        bal = await get_balance(query.from_user.id)
        await query.message.edit_text(
            "Сброшено.\n" + format_settings_text(settings, balance=bal),
            reply_markup=build_settings_keyboard(settings),
        )
        return

    if parts[0] == "set" and len(parts) == 3:
        key = parts[1]
        value = parts[2]
        settings = get_user_settings(context)
        if key in settings:
            settings[key] = value
        bal = await get_balance(query.from_user.id)

        await query.message.edit_text(
            format_settings_text(settings, balance=bal),
            reply_markup=build_settings_keyboard(settings),
        )


# ---------- Регистрация ----------

def register_user_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("model", model_menu_command))
    app.add_handler(CommandHandler("buy", buy_menu_command))

    app.add_handler(CallbackQueryHandler(buy_callback, pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(settings_callback))

    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_buttons)
    )
