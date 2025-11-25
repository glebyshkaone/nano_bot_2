import os
import json
import math
import logging
from io import BytesIO
from pathlib import Path

import httpx
import replicate
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
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

logger.info("Starting nano-bot (UI + refs + tokens + admin)")

# ----------------------------------------
# Переменные окружения
# ----------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

# список админов через запятую: ADMIN_IDS=12345,67890
ADMIN_IDS: list[int] = []
_admin_ids_raw = os.getenv("ADMIN_IDS", "").strip()
if _admin_ids_raw:
    try:
        ADMIN_IDS = [int(x) for x in _admin_ids_raw.split(",") if x.strip()]
    except ValueError:
        logger.error("ADMIN_IDS env parse error, value=%r", _admin_ids_raw)

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set")

if not REPLICATE_API_TOKEN:
    raise ValueError("REPLICATE_API_TOKEN not set")

logger.info(
    "REPLICATE_API_TOKEN prefix: %s..., length: %s",
    REPLICATE_API_TOKEN[:8],
    len(REPLICATE_API_TOKEN),
)

# ----------------------------------------
# Файлы хранения
# ----------------------------------------
TOKENS_FILE = Path("user_tokens.json")
USERS_FILE = Path("users.json")
TOKENS_PER_IMAGE = 150  # 1 генерация = 150 пользовательских токенов


# ---------- Токены ----------
def load_token_store() -> dict[int, int]:
    if TOKENS_FILE.exists():
        try:
            with TOKENS_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): int(v) for k, v in data.items()}
        except Exception as e:
            logger.error("Failed to load token store: %s", e)
    return {}


def save_token_store(store: dict[int, int]) -> None:
    try:
        with TOKENS_FILE.open("w", encoding="utf-8") as f:
            json.dump({str(k): int(v) for k, v in store.items()}, f)
    except Exception as e:
        logger.error("Failed to save token store: %s", e)


TOKEN_STORE: dict[int, int] = load_token_store()


def get_balance(user_id: int) -> int:
    return int(TOKEN_STORE.get(user_id, 0))


def add_tokens(user_id: int, amount: int) -> None:
    TOKEN_STORE[user_id] = get_balance(user_id) + amount
    save_token_store(TOKEN_STORE)


def deduct_tokens(user_id: int, amount: int) -> bool:
    balance = get_balance(user_id)
    if balance < amount:
        return False
    TOKEN_STORE[user_id] = balance - amount
    save_token_store(TOKEN_STORE)
    return True


# ---------- Пользователи ----------
def load_users() -> dict[int, dict]:
    if USERS_FILE.exists():
        try:
            with USERS_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception as e:
            logger.error("Failed to load users: %s", e)
    return {}


def save_users(store: dict[int, dict]) -> None:
    try:
        with USERS_FILE.open("w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in store.items()}, f, ensure_ascii=False)
    except Exception as e:
        logger.error("Failed to save users: %s", e)


USERS: dict[int, dict] = load_users()


def register_user(telegram_user) -> None:
    """Сохраняем пользователя при любом взаимодействии."""
    if not telegram_user:
        return

    uid = telegram_user.id
    info = {
        "first_name": telegram_user.first_name,
        "last_name": telegram_user.last_name,
        "username": telegram_user.username,
    }
    prev = USERS.get(uid)
    if prev != info:
        USERS[uid] = info
        save_users(USERS)


# ----------------------------------------
# Настройки модели
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


def format_settings_text(settings: dict, balance: int | None = None) -> str:
    bal_part = f"Ваш баланс: {balance} токенов\n\n" if balance is not None else ""
    return (
        bal_part
        + "Текущие настройки генерации:\n"
        f"• Соотношение сторон: {settings['aspect_ratio']}\n"
        f"• Разрешение: {settings['resolution']}\n"
        f"• Формат: {settings['output_format']}\n"
        f"• Фильтр безопасности: {settings['safety_filter_level']}\n\n"
        f"Стоимость: {TOKENS_PER_IMAGE} токенов за одно изображение.\n\n"
        "Отправь текстовый промт — я сгенерирую картинку по этим настройкам.\n"
        "Можешь также отправить фото с подписью — оно будет использовано как референс."
    )


def build_settings_keyboard(settings: dict) -> InlineKeyboardMarkup:
    ar = settings["aspect_ratio"]
    res = settings["resolution"]
    fmt = settings["output_format"]
    safety = settings["safety_filter_level"]

    def mark(current: str, value: str, label: str) -> str:
        return f"✅ {label}" if current == value else label

    keyboard = [
        [
            InlineKeyboardButton(mark(ar, "1:1", "1:1"), callback_data="set|aspect_ratio|1:1"),
            InlineKeyboardButton(mark(ar, "4:3", "4:3"), callback_data="set|aspect_ratio|4:3"),
            InlineKeyboardButton(
                mark(ar, "16:9", "16:9"), callback_data="set|aspect_ratio|16:9"
            ),
            InlineKeyboardButton(mark(ar, "9:16", "9:16"), callback_data="set|aspect_ratio|9:16"),
        ],
        [
            InlineKeyboardButton(mark(res, "1K", "1K"), callback_data="set|resolution|1K"),
            InlineKeyboardButton(mark(res, "2K", "2K"), callback_data="set|resolution|2K"),
            InlineKeyboardButton(mark(res, "4K", "4K"), callback_data="set|resolution|4K"),
        ],
        [
            InlineKeyboardButton(mark(fmt, "png", "png"), callback_data="set|output_format|png"),
            InlineKeyboardButton(mark(fmt, "jpg", "jpg"), callback_data="set|output_format|jpg"),
        ],
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
        [
            InlineKeyboardButton(
                "🔁 Сбросить к стандартным", callback_data="reset|settings|default"
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("🚀 Старт"), KeyboardButton("🎛 Меню")],
        [KeyboardButton("💰 Баланс"), KeyboardButton("ℹ Помощь")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ----------------------------------------
# Вспомогательные функции
# ----------------------------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ----------------------------------------
# Команды пользователя
# ----------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update.effective_user)
    user_id = update.effective_user.id
    settings = get_user_settings(context)
    balance = get_balance(user_id)
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
    register_user(update.effective_user)
    user_id = update.effective_user.id
    settings = get_user_settings(context)
    balance = get_balance(user_id)
    await update.message.reply_text(
        format_settings_text(settings, balance=balance),
        reply_markup=build_settings_keyboard(settings),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update.effective_user)
    text = (
        "Как пользоваться ботом:\n\n"
        f"• 1 изображение = {TOKENS_PER_IMAGE} токенов.\n"
        "• Пополнить баланс можно, написав @glebyshkaone.\n\n"
        "1. Нажми /menu или кнопку «🎛 Меню».\n"
        "2. Выбери настройки генерации.\n"
        "3. Отправь текстовый промт или фото с подписью.\n"
        "4. Если хватает токенов — я сгенерирую картинку."
    )
    await update.message.reply_text(text)


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update.effective_user)
    user_id = update.effective_user.id
    balance = get_balance(user_id)
    await update.message.reply_text(
        f"Ваш баланс: {balance} токенов.\n\n"
        f"1 изображение = {TOKENS_PER_IMAGE} токенов.\n"
        "Чтобы пополнить баланс, напишите @glebyshkaone."
    )


# ----------------------------------------
# Админ-команды (текстовые)
# ----------------------------------------
async def admin_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update.effective_user)
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("У вас нет доступа к админ-командам.")
        return

    text = (
        "Админ-панель:\n\n"
        "/admin — открыть визуальную админку с кнопками.\n"
        "/add_tokens <telegram_id> <amount> — начислить токены вручную.\n\n"
        "Пример:\n"
        "/add_tokens 123456789 500"
    )
    await update.message.reply_text(text)


async def add_tokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update.effective_user)
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "Использование: /add_tokens <telegram_id> <amount>\n"
            "Пример: /add_tokens 123456789 500"
        )
        return

    try:
        target_id = int(args[0])
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("telegram_id и amount должны быть числами.")
        return

    if amount <= 0:
        await update.message.reply_text("amount должен быть > 0.")
        return

    add_tokens(target_id, amount)
    await update.message.reply_text(
        f"✅ Пользователю {target_id} начислено {amount} токенов.\n"
        f"Новый баланс: {get_balance(target_id)}"
    )


# ----------------------------------------
# Админ-панель (кнопки)
# ----------------------------------------
def build_admin_main_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📋 Пользователи", callback_data="admin|users|0")],
        [InlineKeyboardButton("❓ Помощь по админке", callback_data="admin|help")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update.effective_user)
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("У вас нет доступа к админ-панели.")
        return

    total_users = len(USERS)
    text = (
        "Админ-панель nano-bot 👑\n\n"
        f"Всего пользователей: {total_users}\n\n"
        "Выберите действие:"
    )
    await update.message.reply_text(text, reply_markup=build_admin_main_keyboard())


def build_admin_users_page(page: int, page_size: int = 5) -> tuple[str, InlineKeyboardMarkup]:
    user_ids = sorted(USERS.keys())
    total = len(user_ids)
    if total == 0:
        text = "Пользователей пока нет."
        return text, InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ В админ-панель", callback_data="admin|back|main")]]
        )

    total_pages = max(1, math.ceil(total / page_size))
    page = max(0, min(page, total_pages - 1))

    start_idx = page * page_size
    end_idx = start_idx + page_size
    slice_ids = user_ids[start_idx:end_idx]

    lines = [
        f"Пользователи (стр. {page + 1}/{total_pages}, всего: {total})",
        "",
    ]
    keyboard_rows = []

    for uid in slice_ids:
        info = USERS.get(uid, {})
        username = info.get("username")
        first_name = info.get("first_name") or ""
        last_name = info.get("last_name") or ""
        name = (first_name + " " + (last_name or "")).strip() or "Без имени"
        balance = get_balance(uid)

        tag = f"@{username}" if username else ""
        lines.append(f"{uid} {tag} — {name} — {balance} токенов")

        btn_label = f"{name} ({balance})"
        keyboard_rows.append(
            [InlineKeyboardButton(btn_label, callback_data=f"admin|user|{uid}|{page}")]
        )

    # навигация
    nav_row = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton("◀️", callback_data=f"admin|users|{page - 1}")
        )
    if page < total_pages - 1:
        nav_row.append(
            InlineKeyboardButton("▶️", callback_data=f"admin|users|{page + 1}")
        )
    if nav_row:
        keyboard_rows.append(nav_row)

    keyboard_rows.append(
        [InlineKeyboardButton("⬅️ В админ-панель", callback_data="admin|back|main")]
    )

    text = "\n".join(lines)
    return text, InlineKeyboardMarkup(keyboard_rows)


def build_admin_user_detail(uid: int, page: int) -> tuple[str, InlineKeyboardMarkup]:
    info = USERS.get(uid, {})
    username = info.get("username")
    first_name = info.get("first_name") or ""
    last_name = info.get("last_name") or ""
    name = (first_name + " " + (last_name or "")).strip() or "Без имени"
    balance = get_balance(uid)

    lines = [
        "Карточка пользователя 👤",
        "",
        f"ID: {uid}",
        f"Имя: {name}",
        f"Username: @{username}" if username else "Username: —",
        f"Баланс: {balance} токенов",
        "",
        "Начислить токены:",
    ]

    keyboard = [
        [
            InlineKeyboardButton("+150", callback_data=f"admin|add|{uid}|150|{page}"),
            InlineKeyboardButton("+500", callback_data=f"admin|add|{uid}|500|{page}"),
            InlineKeyboardButton("+1000", callback_data=f"admin|add|{uid}|1000|{page}"),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Назад к списку", callback_data=f"admin|users|{page}"
            )
        ],
    ]

    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.answer("Нет доступа", show_alert=True)
        return

    await query.answer()
    data = query.data or ""
    parts = data.split("|")

    # форматы:
    # admin|users|page
    # admin|help
    # admin|back|main
    # admin|user|uid|page
    # admin|add|uid|amount|page

    if len(parts) < 2:
        return

    action = parts[1]

    if action == "help":
        text = (
            "Админ-панель:\n\n"
            "• «Пользователи» — список всех юзеров, их баланс.\n"
            "• В карточке пользователя можно быстро начислить +150 / +500 / +1000 токенов.\n\n"
            "Для произвольной суммы есть команда:\n"
            "/add_tokens <telegram_id> <amount>"
        )
        await query.message.edit_text(text, reply_markup=build_admin_main_keyboard())
        return

    if action == "back" and len(parts) >= 3 and parts[2] == "main":
        total_users = len(USERS)
        text = (
            "Админ-панель nano-bot 👑\n\n"
            f"Всего пользователей: {total_users}\n\n"
            "Выберите действие:"
        )
        await query.message.edit_text(text, reply_markup=build_admin_main_keyboard())
        return

    if action == "users" and len(parts) >= 3:
        try:
            page = int(parts[2])
        except ValueError:
            page = 0
        text, kb = build_admin_users_page(page)
        await query.message.edit_text(text, reply_markup=kb)
        return

    if action == "user" and len(parts) >= 4:
        try:
            uid = int(parts[2])
            page = int(parts[3])
        except ValueError:
            return
        text, kb = build_admin_user_detail(uid, page)
        await query.message.edit_text(text, reply_markup=kb)
        return

    if action == "add" and len(parts) >= 5:
        try:
            uid = int(parts[2])
            amount = int(parts[3])
            page = int(parts[4])
        except ValueError:
            return

        add_tokens(uid, amount)
        new_balance = get_balance(uid)
        await query.answer(f"Начислено {amount} токенов (баланс {new_balance})", show_alert=False)

        text, kb = build_admin_user_detail(uid, page)
        await query.message.edit_text(text, reply_markup=kb)
        return


# ----------------------------------------
# Reply-кнопки пользователя
# ----------------------------------------
async def handle_reply_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update.effective_user)
    text = (update.message.text or "").strip()

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

    # Всё остальное — текстовый промт
    await handle_text_prompt(update, context)


# ----------------------------------------
# Инлайн-кнопки настроек генерации
# ----------------------------------------
async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data or ""
    if not data or not data.startswith(("set|", "reset|", "open|")):
        return  # остальные колбеки — для админки

    parts = data.split("|")
    action = parts[0]

    if action == "reset":
        context.user_data.clear()
        settings = get_user_settings(context)
        balance = get_balance(query.from_user.id)
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

        balance = get_balance(query.from_user.id)
        await query.message.edit_text(
            format_settings_text(settings, balance=balance),
            reply_markup=build_settings_keyboard(settings),
        )
        return

    if action == "open" and len(parts) >= 2:
        target = parts[1]
        if target == "settings":
            settings = get_user_settings(context)
            balance = get_balance(query.from_user.id)
            await query.message.edit_text(
                format_settings_text(settings, balance=balance),
                reply_markup=build_settings_keyboard(settings),
            )
        elif target == "help":
            await query.message.edit_text(
                "Это nano-bot на базе google/nano-banana-pro.\n\n"
                "Используй /menu, чтобы настроить генерацию, и просто отправляй промты.",
            )
        return


# ----------------------------------------
# Генерация через nano-banana
# ----------------------------------------
async def generate_with_nano_banana(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    image_urls: list[str] | None = None,
) -> None:
    register_user(update.effective_user)
    user_id = update.effective_user.id
    balance = get_balance(user_id)

    if balance < TOKENS_PER_IMAGE:
        await update.message.reply_text(
            f"Недостаточно токенов: на балансе {balance}, нужно {TOKENS_PER_IMAGE}.\n\n"
            "Напишите @glebyshkaone, чтобы пополнить баланс."
        )
        return

    settings = get_user_settings(context)

    logger.info("Prompt: %s", prompt)
    logger.info("Settings: %s", settings)
    logger.info("Image refs: %s", image_urls)

    await update.message.reply_text("Генерирую картинку, подожди 5–20 секунд… ⚙️")

    try:
        input_payload = {
            "prompt": prompt,
            "aspect_ratio": settings["aspect_ratio"],
            "resolution": settings["resolution"],
            "output_format": settings["output_format"],
            "safety_filter_level": settings["safety_filter_level"],
        }

        if image_urls:
            input_payload["image_input"] = image_urls

        output = replicate.run(
            "google/nano-banana-pro",
            input=input_payload,
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

        # Списываем токены только после успешной отправки изображения
        if deduct_tokens(user_id, TOKENS_PER_IMAGE):
            new_balance = get_balance(user_id)
            await update.message.reply_text(
                f"Списано {TOKENS_PER_IMAGE} токенов. Новый баланс: {new_balance}."
            )
        else:
            await update.message.reply_text(
                "Изображение сгенерировано, но не удалось списать токены — обратитесь к администратору."
            )

    except Exception as e:
        logger.exception("Ошибка при генерации/отправке")
        await update.message.reply_text(
            f"Произошла ошибка при генерации: {e}\n"
            "Если ошибка повторяется — напишите @glebyshkaone."
        )


# ----------------------------------------
# Текстовый промт
# ----------------------------------------
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


# ----------------------------------------
# Фото как референс
# ----------------------------------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update.effective_user)
    message = update.message
    if not message or not message.photo:
        return

    photo = message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_url = file.file_path

    prompt = (message.caption or "").strip()
    if not prompt:
        prompt = "image to image generation"

    await generate_with_nano_banana(update, context, prompt, image_urls=[image_url])


# ----------------------------------------
# Точка входа
# ----------------------------------------
def main() -> None:
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Пользовательские команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("balance", balance_command))

    # Админ-команды
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("admin_help", admin_help_command))
    application.add_handler(CommandHandler("add_tokens", add_tokens_command))

    # CallbackQuery: сначала админка, потом настройки генерации
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin\\|"))
    application.add_handler(CallbackQueryHandler(settings_callback))

    # Фото и текст
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_buttons)
    )

    application.run_polling()


if __name__ == "__main__":
    main()
