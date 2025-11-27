from io import BytesIO
import logging
from datetime import datetime, timezone

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
from core.supabase import fetch_generations, log_generation, count_generations_since
from core.generators import run_model
from core.api_tokens import create_api_token_for_user
from .keyboards import build_reply_keyboard

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------

STARS_PER_150_TOKENS = 25
PAYLOAD_PREFIX = "buy_tokens:"
TOKEN_PACKS = [500, 1000, 1500]
CUSTOM_TOKENS_KEY = "awaiting_custom_tokens"
FLUX_INPUT_KEY = "awaiting_flux_input"  # seed / safety / strength
API_BASE_URL_FOR_PS = "https://nanobot.glebmishin72.workers.dev"
FREE_REMOVE_BG_PER_DAY = 5


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
        "Пополнить токены через Telegram Stars: /buy\n"
        "Получить токен для Photoshop-плагина: /ps_token"
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
        "\nПополнение токенов через Telegram Stars: /buy\n"
        "Токен для Photoshop-плагина: /ps_token\n\n"
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


async def ps_token_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Выдаём токен для Photoshop-плагина."""
    await register_user(update.effective_user)
    user_id = update.effective_user.id

    token = await create_api_token_for_user(user_id)

    text = (
        "🔑 Токен для Photoshop-плагина Nano Bot:\n\n"
        f"`{token}`\n\n"
        "1. Скопируйте этот токен и вставьте его в настройках плагина в поле *NanoBot Token*.\n"
        f"2. В поле *API Base URL* укажите:\n`{API_BASE_URL_FOR_PS}`\n\n"
        "Храните токен как пароль — по нему считается ваш баланс токенов."
    )

    await update.message.reply_text(text, parse_mode="Markdown")


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
        pricing = info.get("pricing_text", f"{info['base_cost']} токенов")
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
# GENERATION
# ---------------------------------------------------------


def _today_utc_iso() -> str:
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return today.isoformat()


async def get_remove_bg_free_left(user_id: int) -> int:
    model_id = MODEL_INFO["remove_bg"]["replicate"]
    used = await count_generations_since(user_id, model_id, _today_utc_iso())
    return max(0, FREE_REMOVE_BG_PER_DAY - used)


async def get_effective_cost(user_id: int, settings: dict) -> tuple[int, int | None]:
    model_key = settings.get("model", "banana")
    if model_key == "remove_bg":
        free_left = await get_remove_bg_free_left(user_id)
        if free_left > 0:
            return 0, free_left
        return MODEL_INFO["remove_bg"]["base_cost"], 0

    return get_generation_cost_tokens(settings), None


def build_run_message(model_key: str, cost: int, free_left: int | None) -> str:
    if model_key == "remove_bg":
        if cost == 0:
            remaining = max(0, (free_left or 1) - 1)
            return (
                "Удаляю фон… Бесплатно, осталось "
                f"{remaining} из {FREE_REMOVE_BG_PER_DAY} на сегодня."
            )
        return f"Удаляю фон… Стоимость {cost} токенов."

    return "Генерация запущена… ⚙️"


def free_run_message(model_key: str, free_left: int | None) -> str | None:
    if model_key == "remove_bg" and free_left is not None:
        remaining = max(0, (free_left or 1) - 1)
        return (
            "Фон удалён бесплатно. Осталось "
            f"{remaining} из {FREE_REMOVE_BG_PER_DAY} на сегодня."
        )

    return None

async def generate_with_nano_banana(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    image_urls=None,
) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id
    settings = get_user_settings(context)
    model_key = settings.get("model", "banana")

    cost, free_left = await get_effective_cost(user_id, settings)
    balance = await get_balance(user_id)

    if cost > 0 and balance < cost:
        await update.message.reply_text(
            f"Недостаточно токенов: нужно {cost}, у вас {balance}.\n"
            "Пополните баланс через /buy."
        )
        return

    if model_key == "remove_bg" and not image_urls:
        await update.message.reply_text("Пришлите фото, чтобы удалить фон.")
        return

    await update.message.reply_text(build_run_message(model_key, cost, free_left))

    try:
        image_url, img_bytes = await run_model(
            prompt,
            settings,
            image_urls=image_urls,
        )

        used_cost = 0
        new_balance = balance
        if cost > 0:
            ok, used_cost, new_balance = await deduct_tokens(
                user_id, settings, override_cost=cost
            )
            if not ok:
                logger.error(
                    "Не удалось списать токены после успешной генерации "
                    f"(user_id={user_id}, expected_cost={cost})"
                )
                used_cost = 0
                new_balance = await get_balance(user_id)

        if img_bytes:
            bio = BytesIO(img_bytes)
            bio.name = f"nano-bot.{settings.get('output_format', 'png')}"
            bio.seek(0)
            await update.message.reply_photo(photo=bio)
        else:
            await update.message.reply_photo(photo=image_url)

        if used_cost > 0:
            await update.message.reply_text(
                f"Списано {used_cost} токенов. Новый баланс: {new_balance}."
            )
        else:
            await update.message.reply_text(
                free_run_message(model_key, free_left)
                or "Картинка сгенерирована без списания токенов."
            )

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

    settings = get_user_settings(context)
    if settings.get("model") == "remove_bg":
        await update.message.reply_text("Отправьте фото, чтобы удалить фон с изображения.")
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
# REPLY BUTTONS + CUSTOM INPUT
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

    # --- кастомный ввод параметров FLUX ---
    pending = context.user_data.get(FLUX_INPUT_KEY)
    if pending:
        context.user_data[FLUX_INPUT_KEY] = None
        settings = get_user_settings(context)

        if pending == "seed":
            value = text.strip()
            if value.lower() == "off":
                settings["seed"] = "off"
                msg = "Seed отключён (off)."
            else:
                try:
                    iv = int(value)
                    settings["seed"] = str(iv)
                    msg = f"Seed установлен: {iv}."
                except ValueError:
                    msg = "Seed должен быть целым числом или off. Значение не изменено."
        elif pending == "safety_tolerance":
            try:
                iv = int(float(text.replace(",", ".")))
                iv = max(1, min(6, iv))
                settings["safety_tolerance"] = str(iv)
                msg = f"Safety установлен: {iv} (1 — строгий, 6 — максимально свободный)."
            except ValueError:
                msg = "Safety должен быть числом от 1 до 6. Значение не изменено."
        elif pending == "image_prompt_strength":
            try:
                fv = float(text.replace(",", "."))
                fv = max(0.0, min(1.0, fv))
                settings["image_prompt_strength"] = f"{fv:.2f}".rstrip("0").rstrip(".")
                msg = f"Strength установлен: {settings['image_prompt_strength']}."
            except ValueError:
                msg = "Strength должен быть числом от 0 до 1. Значение не изменено."
        else:
            msg = "Неизвестный параметр, значение не изменено."

        balance = await get_balance(update.effective_user.id)
        await update.message.reply_text(
            msg + "\n\n" + format_settings_text(settings, balance=balance),
            reply_markup=build_settings_keyboard(settings),
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

    if data.startswith("buy_"):
        return

    await query.answer()

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

    if action == "input" and len(parts) == 2:
        param = parts[1]
        context.user_data[FLUX_INPUT_KEY] = param
        if param == "seed":
            text = (
                "Введите значение seed (целое число) или напишите off, чтобы отключить.\n"
                "Пример: 42"
            )
        elif param == "safety_tolerance":
            text = "Введите значение safety от 1 до 6 (1 — строгий фильтр, 6 — максимально свободный)."
        elif param == "image_prompt_strength":
            text = "Введите strength от 0 до 1 (0.1 — слабое влияние картинки, 1 — сильное)."
        else:
            text = "Введите новое значение параметра."

        await query.message.reply_text(text)
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
    app.add_handler(CommandHandler("ps_token", ps_token_command))

    app.add_handler(CallbackQueryHandler(buy_callback, pattern=r"^buy_"))
    app.add_handler(CallbackQueryHandler(settings_callback))

    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_buttons)
    )
