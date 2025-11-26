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
from core.registry import register_user
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

# ---------------------------------------------------------
# CONSTANTS FOR PAYMENTS
# ---------------------------------------------------------

# 150 токенов = 25 звёзд
STARS_PER_150_TOKENS = 25
PAYLOAD_PREFIX = "buy_tokens:"
TOKEN_PACKS = [500, 1000, 1500]
CUSTOM_TOKENS_KEY = "awaiting_custom_tokens"


def tokens_to_stars(tokens: int) -> int:
    stars = round(tokens * STARS_PER_150_TOKENS / 150)
    return max(1, stars)


# ---------------------------------------------------------
# BASIC COMMANDS
# ---------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    settings = get_user_settings(context)
    balance = await get_balance(update.effective_user.id)

    text = (
        "Привет! Я nano-bot 🤖\n\n"
        "Отправь текстовый промт — я сгенерирую картинку.\n"
        "Можно отправить фото с подписью — изображение станет референсом.\n\n"
        "Пополнить токены через Telegram Stars: /buy"
    )

    await update.message.reply_text(text, reply_markup=build_reply_keyboard())
    await update.message.reply_text(
        format_settings_text(settings, balance=balance),
        reply_markup=build_settings_keyboard(settings),
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_user_settings(context)
    balance = await get_balance(update.effective_user.id)
    await update.message.reply_text(
        format_settings_text(settings, balance=balance),
        reply_markup=build_settings_keyboard(settings),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)

    lines = ["Как пользоваться ботом:\n"]

    for key, info in MODEL_INFO.items():
        emoji = info.get("emoji", "🧠")
        pricing = info.get("pricing_text", f"{info['base_cost']} токенов")
        lines.append(f"• {emoji} {info['label']} — {pricing}")

    lines.append(
        "\nПополнение токенов через Telegram Stars: /buy\n\n"
        "Команды:\n"
        "/menu — настройки генерации\n"
        "/model — выбор модели\n"
        "/balance — баланс токенов\n"
        "/history — последние генерации\n"
    )

    await update.message.reply_text("\n".join(lines))


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id
    balance = await get_balance(user_id)

    lines = [f"Ваш баланс: {balance} токенов.\n", "Тарифы генерации:"]

    for key, info in MODEL_INFO.items():
        emoji = info.get("emoji", "🧠")
        pricing = info.get("pricing_text", f"{info['base_cost']} токенов")
        lines.append(f"• {emoji} {info['label']} — {pricing}")

    lines.append("")
    lines.append("Пополнение через Telegram Stars (/buy):")
    for t in TOKEN_PACKS:
        stars = tokens_to_stars(t)
        lines.append(f"• {t} токенов — {stars}⭐")
    lines.append("• Другое количество — также считается по этому курсу.")

    await update.message.reply_text("\n".join(lines))


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


# ---------------------------------------------------------
# MODEL MENU
# ---------------------------------------------------------

async def model_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    settings = get_user_settings(context)
    current_model = settings["model"]

    lines = ["🧠 Выбор модели генерации:\n"]
    for key, info in MODEL_INFO.items():
        emoji = info.get("emoji", "🧠")
        pricing = info.get("pricing_text", f"{info['base_cost']} tokенов")
        prefix = "✅ " if key == current_model else ""
        lines.append(f"{prefix}{emoji} {info['label']} — {pricing}")
    lines.append("")
    lines.append("Нажми кнопку ниже, чтобы сменить модель.")

    buttons_rows = []
    row = []
    for key, info in MODEL_INFO.items():
        emoji = info.get("emoji", "🧠")
        prefix = "✅ " if key == current_model else ""
        row.append(
            InlineKeyboardButton(
                f"{prefix}{emoji} {info['label']}",
                callback_data=f"set|model|{key}",
            )
        )
        if len(row) == 2:
            buttons_rows.append(row)
            row = []
    if row:
        buttons_rows.append(row)

    buttons_rows.append(
        [InlineKeyboardButton("⬅ Вернуться в меню", callback_data="back|menu")]
    )

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons_rows),
    )


# ---------------------------------------------------------
# GENERATION (CHARGE TOKENS ONLY ON SUCCESS)
# ---------------------------------------------------------

async def generate_with_nano_banana(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    image_urls=None,
) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id
    settings = get_user_settings(context)

    # 1. Проверяем баланс (без списания)
    cost = get_generation_cost_tokens(settings)
    balance = await get_balance(user_id)

    if balance < cost:
        await update.message.reply_text(
            f"Недостаточно токенов: нужно {cost}, у вас {balance}.\n"
            "Пополните баланс через /buy."
        )
        return

    await update.message.reply_text("Генерация запущена… ⚙️")

    try:
        # 2. Генерация
        image_url, img_bytes = await run_model(
            prompt,
            settings,
            image_urls=image_urls,
        )

        # 3. Успешная генерация → списываем токены
        ok, used_cost, new_balance = await deduct_tokens(user_id, settings)
        if not ok:
            logger.error(
                "Не удалось списать токены после успешной генерации "
                f"(user_id={user_id}, expected_cost={cost})"
            )
            used_cost = 0
            new_balance = await get_balance(user_id)

        # 4. Отправляем изображение
        bio = BytesIO(img_bytes)
        bio.name = f"nano-bot.{settings.get('output_format', 'png')}"
        bio.seek(0)

        await update.message.reply_photo(photo=bio)

        # 5. Сообщение о списании
        if used_cost > 0:
            await update.message.reply_text(
                f"Списано {used_cost} токенов. Новый баланс: {new_balance}."
            )
        else:
            await update.message.reply_text(
                "Картинка сгенерирована, но токены не были списаны. "
                "Если что-то идёт не так — напишите @glebyshkaone."
            )

        # 6. Логирование
        await log_generation(
            user_id=user_id,
            prompt=prompt,
            image_url=image_url,
            settings=settings,
            tokens_spent=used_cost or cost,
        )

    except Exception as e:
        logger.exception("Ошибка при генерации/отправке")
        await update.message.reply_text(
            "Произошла ошибка при генерации, токены не списаны.\n"
            f"Детали: {e}"
        )


# ---------------------------------------------------------
# TEXT & PHOTO PROMPTS
# ---------------------------------------------------------

async def handle_text_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    prompt = update.message.text.strip()
    if not prompt or prompt.startswith("/"):
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

    prompt = (message.caption or "").strip() or "image to image"
    await generate_with_nano_banana(update, context, prompt, image_urls=[image_url])


# ---------------------------------------------------------
# BUY TOKENS VIA TELEGRAM STARS
# ---------------------------------------------------------

async def buy_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)

    lines = ["Пополнение токенов через Telegram Stars:\n"]
    for t in TOKEN_PACKS:
        stars = tokens_to_stars(t)
        lines.append(f"• {t} токенов — {stars}⭐")
    lines.append("\nИли выберите «Другое количество» и введите нужное число токенов.")

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
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data or ""
    chat_id = query.message.chat_id

    # Готовые паки
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
            description="Пакет токенов для nano-bot.",
            payload=payload,
            provider_token="",  # для Stars — пустая строка
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

    # Произвольное количество токенов
    if data == "buy_custom":
        context.user_data[CUSTOM_TOKENS_KEY] = True
        await query.message.reply_text(
            "Введите, сколько токенов вы хотите купить (целое число). "
            "Я посчитаю стоимость в ⭐ и пришлю счёт."
        )
        return


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    payload = query.invoice_payload or ""

    if not payload.startswith(PAYLOAD_PREFIX):
        await query.answer(ok=False, error_message="Неверный товар. Напишите @glebyshkaone.")
        return

    await query.answer(ok=True)


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        "Можно продолжать генерировать ✨"
    )


# ---------------------------------------------------------
# REPLY BUTTONS + CUSTOM TOKEN INPUT
# ---------------------------------------------------------

async def handle_reply_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    text = (update.message.text or "").strip()

    # --- кастомный ввод токенов для покупки ---
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
            f"{tokens} токенов = {stars}⭐.\n"
            "Сейчас пришлю счёт."
        )

        prices = [LabeledPrice(label=f"{tokens} токенов", amount=stars)]
        payload = f"{PAYLOAD_PREFIX}{tokens}"

        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=f"{tokens} токенов",
            description="Пакет токенов для nano-bot.",
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
        return

    # --- обычные reply-кнопки ---
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

    # Остальное — текстовый промт
    await handle_text_prompt(update, context)


# ---------------------------------------------------------
# SETTINGS CALLBACK
# ---------------------------------------------------------

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    data = query.data or ""

    # оплатные «buy_» обрабатываются отдельно
    if data.startswith("buy_"):
        return

    await query.answer()

    # возврат в меню
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
            "Настройки сброшены.\n\n" +
            format_settings_text(settings, balance=balance),
            reply_markup=build_settings_keyboard(settings),
        )
        return

    if action == "set" and len(parts) == 3:
        key = parts[1]
        value = parts[2]

        settings = get_user_settings(context)
        # обновляем только известные ключи
        if key in settings:
            settings[key] = value

        balance = await get_balance(query.from_user.id)
        await query.message.edit_text(
            format_settings_text(settings, balance=balance),
            reply_markup=build_settings_keyboard(settings),
        )


# ---------------------------------------------------------
# REGISTRATION
# ---------------------------------------------------------

def register_user_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("model", model_menu_command))
    app.add_handler(CommandHandler("buy", buy_menu_command))

    # inline-кнопки покупки
    app.add_handler(CallbackQueryHandler(buy_callback, pattern=r"^buy_"))

    # настройки
    app.add_handler(CallbackQueryHandler(settings_callback))

    # оплатные хендлеры
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    # фото и текст
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_buttons)
    )
