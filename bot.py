import os
import logging
from io import BytesIO
from typing import Optional, List, Dict

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

logger.info("Starting nano-bot with Supabase storage + admin panel + history")

# ----------------------------------------
# Env
# ----------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS: List[int] = []
if ADMIN_IDS_RAW:
    try:
        ADMIN_IDS = [int(x) for x in ADMIN_IDS_RAW.split(",") if x.strip()]
    except ValueError:
        logger.error("Failed to parse ADMIN_IDS=%r", ADMIN_IDS_RAW)

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set")

if not REPLICATE_API_TOKEN:
    raise ValueError("REPLICATE_API_TOKEN not set")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")

SUPABASE_REST_URL = SUPABASE_URL.rstrip("/") + "/rest/v1"
SUPABASE_HEADERS_BASE = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}

TOKENS_PER_IMAGE = 150  # стоимость 1 поколения

# ----------------------------------------
# Настройки модели
# ----------------------------------------
DEFAULT_SETTINGS = {
    "aspect_ratio": "4:3",
    "resolution": "2K",
    "output_format": "png",
    "safety_filter_level": "block_only_high",
}


def get_user_settings(context: ContextTypes.DEFAULT_TYPE) -> Dict:
    data = context.user_data
    for k, v in DEFAULT_SETTINGS.items():
        data.setdefault(k, v)
    return data


def format_settings_text(settings: Dict, balance: Optional[int] = None) -> str:
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


def build_settings_keyboard(settings: Dict) -> InlineKeyboardMarkup:
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
            InlineKeyboardButton(mark(ar, "16:9", "16:9"), callback_data="set|aspect_ratio|16:9"),
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
            InlineKeyboardButton("🔁 Сбросить к стандартным", callback_data="reset|settings|default")
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("🚀 Старт"), KeyboardButton("🎛 Меню")],
        [KeyboardButton("💰 Баланс"), KeyboardButton("📜 История"), KeyboardButton("ℹ Помощь")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ----------------------------------------
# Supabase helpers
# ----------------------------------------
async def supabase_get_user(user_id: int) -> Optional[Dict]:
    params = {
        "id": f"eq.{user_id}",
        "select": "id,username,first_name,last_name,balance,created_at,updated_at",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_REST_URL}/telegram_users",
            headers=SUPABASE_HEADERS_BASE,
            params=params,
            timeout=10.0,
        )
    resp.raise_for_status()
    data = resp.json()
    return data[0] if data else None


async def supabase_insert_user(payload: Dict) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_REST_URL}/telegram_users",
            headers=SUPABASE_HEADERS_BASE,
            params={"select": "id"},
            json=[payload],
            timeout=10.0,
        )
    resp.raise_for_status()


async def supabase_update_user(user_id: int, payload: Dict) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{SUPABASE_REST_URL}/telegram_users",
            headers=SUPABASE_HEADERS_BASE,
            params={"id": f"eq.{user_id}", "select": "id"},
            json=payload,
            timeout=10.0,
        )
    resp.raise_for_status()


async def supabase_fetch_recent_users(limit: int = 20) -> List[Dict]:
    params = {
        "select": "id,username,first_name,last_name,balance,created_at",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_REST_URL}/telegram_users",
            headers=SUPABASE_HEADERS_BASE,
            params=params,
            timeout=10.0,
        )
    resp.raise_for_status()
    return resp.json()


async def supabase_search_users(query: str, limit: int = 20) -> List[Dict]:
    """Поиск по id или по username/имени (ilike)."""
    params = {
        "select": "id,username,first_name,last_name,balance,created_at",
        "limit": str(limit),
    }

    # Если строка — целое число, ищем по id
    if query.isdigit():
        params["id"] = f"eq.{int(query)}"
    else:
        q = query.strip()
        or_param = f"(username.ilike.*{q}*,first_name.ilike.*{q}*,last_name.ilike.*{q}*)"
        params["or"] = or_param

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_REST_URL}/telegram_users",
            headers=SUPABASE_HEADERS_BASE,
            params=params,
            timeout=10.0,
        )
    resp.raise_for_status()
    return resp.json()


# ----- admin_actions -----
async def log_admin_action(
    admin_id: int,
    target_id: int,
    action: str,
    amount: int,
    note: Optional[str] = None,
) -> None:
    payload = {
        "admin_id": admin_id,
        "target_user_id": target_id,
        "action": action,
        "amount": amount,
        "note": note,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_REST_URL}/admin_actions",
            headers=SUPABASE_HEADERS_BASE,
            json=[payload],
            timeout=10.0,
        )
    # если таблица не создана / RLS блокирует — логируем, но не ломаем бота
    if resp.status_code >= 300:
        logger.warning("Failed to log admin_action: %s %s", resp.status_code, resp.text)


# ----- generations -----
async def log_generation(
    user_id: int,
    prompt: str,
    image_url: str,
    settings: Dict,
    tokens_spent: int,
) -> None:
    payload = {
        "user_id": user_id,
        "prompt": prompt,
        "image_url": image_url,
        "tokens_spent": tokens_spent,
        "model": "google/nano-banana-pro",
        "aspect_ratio": settings.get("aspect_ratio"),
        "resolution": settings.get("resolution"),
        "output_format": settings.get("output_format"),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_REST_URL}/generations",
            headers=SUPABASE_HEADERS_BASE,
            json=[payload],
            timeout=10.0,
        )
    if resp.status_code >= 300:
        logger.warning("Failed to log generation: %s %s", resp.status_code, resp.text)


async def fetch_generations(user_id: int, limit: int = 5) -> List[Dict]:
    params = {
        "select": "id,prompt,image_url,tokens_spent,created_at",
        "user_id": f"eq.{user_id}",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_REST_URL}/generations",
            headers=SUPABASE_HEADERS_BASE,
            params=params,
            timeout=10.0,
        )
    if resp.status_code >= 300:
        logger.warning("Failed to fetch generations: %s %s", resp.status_code, resp.text)
        return []
    return resp.json()


# ----------------------------------------
# User + balance API
# ----------------------------------------
async def register_user(tg_user) -> None:
    """Создаём пользователя в Supabase (если нет) и обновляем имя/username."""
    if not tg_user:
        return

    uid = tg_user.id
    username = tg_user.username
    first_name = tg_user.first_name
    last_name = tg_user.last_name

    try:
        existing = await supabase_get_user(uid)
        if existing:
            payload = {
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "updated_at": "now()",
            }
            await supabase_update_user(uid, payload)
        else:
            payload = {
                "id": uid,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "balance": 0,
            }
            await supabase_insert_user(payload)
    except Exception as e:
        logger.error("register_user error for %s: %s", uid, e)


async def get_balance(user_id: int) -> int:
    try:
        user = await supabase_get_user(user_id)
        if user and isinstance(user.get("balance"), int):
            return user["balance"]
    except Exception as e:
        logger.error("get_balance error: %s", e)
    return 0


async def set_balance(user_id: int, new_balance: int) -> None:
    try:
        await supabase_update_user(user_id, {"balance": new_balance, "updated_at": "now()"})
    except Exception as e:
        logger.error("set_balance error: %s", e)


async def add_tokens(user_id: int, amount: int) -> int:
    current = await get_balance(user_id)
    new_balance = max(0, current + amount)
    await set_balance(user_id, new_balance)
    return new_balance


async def subtract_tokens(user_id: int, amount: int) -> int:
    """Списать токены вручную (админом), не даём уйти ниже 0."""
    if amount <= 0:
        return await get_balance(user_id)
    current = await get_balance(user_id)
    new_balance = max(0, current - amount)
    await set_balance(user_id, new_balance)
    return new_balance


async def deduct_tokens(user_id: int, amount: int) -> bool:
    """Списать токены при генерации, если хватает."""
    current = await get_balance(user_id)
    if current < amount:
        return False
    new_balance = current - amount
    await set_balance(user_id, new_balance)
    return True


# ----------------------------------------
# Команды пользователя
# ----------------------------------------
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


# ----------------------------------------
# Админские команды
# ----------------------------------------
async def admin_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
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
    await register_user(update.effective_user)
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
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

    new_balance = await add_tokens(target_id, amount)
    await log_admin_action(admin_id, target_id, "add_tokens_command", amount)

    # Ответ админу
    await update.message.reply_text(
        f"✅ Пользователю {target_id} начислено {amount} токенов.\n"
        f"Новый баланс: {new_balance}"
    )

    # Уведомление пользователю
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"🎉 Ваш баланс пополнен на {amount} токенов.\n"
                f"Текущий баланс: {new_balance} токенов.\n\n"
                "Можете продолжать генерации в боте 🙂"
            ),
        )
    except Exception as e:
        logger.warning("Не удалось отправить уведомление пользователю %s: %s", target_id, e)


# ------- Админ-панель с кнопками -------
def build_admin_main_keyboard(users: List[Dict]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []

    for u in users:
        uid = u["id"]
        balance = u.get("balance", 0)
        first_name = u.get("first_name") or ""
        last_name = u.get("last_name") or ""
        name = (first_name + " " + (last_name or "")).strip() or "Без имени"
        label = f"{name} ({balance})"
        rows.append([InlineKeyboardButton(label, callback_data=f"admin_user|{uid}")])

    if not rows:
        rows = [[InlineKeyboardButton("Нет пользователей", callback_data="admin_none")]]

    # строка поиска
    rows.append([InlineKeyboardButton("🔎 Поиск", callback_data="admin_search_prompt")])

    return InlineKeyboardMarkup(rows)


def build_admin_user_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("+150", callback_data=f"admin_add|{uid}|150"),
                InlineKeyboardButton("+500", callback_data=f"admin_add|{uid}|500"),
                InlineKeyboardButton("+1000", callback_data=f"admin_add|{uid}|1000"),
            ],
            [
                InlineKeyboardButton("−150", callback_data=f"admin_sub|{uid}|150"),
                InlineKeyboardButton("−500", callback_data=f"admin_sub|{uid}|500"),
                InlineKeyboardButton("−1000", callback_data=f"admin_sub|{uid}|1000"),
            ],
            [
                InlineKeyboardButton("🧹 Обнулить", callback_data=f"admin_zero|{uid}"),
            ],
            [
                InlineKeyboardButton("⬅️ Назад к списку", callback_data="admin_back_main"),
            ],
        ]
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("У вас нет доступа к админ-панели.")
        return

    users = await supabase_fetch_recent_users(limit=20)
    total = len(users)

    text_lines = ["Админ-панель nano-bot 👑", ""]
    text_lines.append(f"Показаны последние {total} пользователей.")
    text_lines.append("")
    text_lines.append("Выберите пользователя, чтобы начислить/списать токены:")
    kb = build_admin_main_keyboard(users)

    context.user_data["admin_search_mode"] = False

    await update.message.reply_text("\n".join(text_lines), reply_markup=kb)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    admin_id = query.from_user.id
    if not is_admin(admin_id):
        await query.answer("Нет доступа", show_alert=True)
        return

    data = query.data or ""
    if data == "admin_none":
        await query.answer()
        return

    # Назад к списку
    if data == "admin_back_main":
        await query.answer()
        users = await supabase_fetch_recent_users(limit=20)
        total = len(users)
        text_lines = ["Админ-панель nano-bot 👑", ""]
        text_lines.append(f"Показаны последние {total} пользователей.")
        text_lines.append("")
        text_lines.append("Выберите пользователя, чтобы начислить/списать токены:")
        kb = build_admin_main_keyboard(users)
        context.user_data["admin_search_mode"] = False
        await query.message.edit_text("\n".join(text_lines), reply_markup=kb)
        return

    # Запрос поиска
    if data == "admin_search_prompt":
        await query.answer()
        context.user_data["admin_search_mode"] = True
        await query.message.edit_text(
            "🔎 Введите ID, username или часть имени для поиска.\n\n"
            "Например:\n"
            "`123456789`\n"
            "`@username`\n"
            "`gleb`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Назад к списку", callback_data="admin_back_main")]]
            ),
        )
        return

    # Карточка пользователя
    if data.startswith("admin_user|"):
        await query.answer()
        _, uid_str = data.split("|", 1)
        try:
            uid = int(uid_str)
        except ValueError:
            return

        user = await supabase_get_user(uid)
        if not user:
            await query.message.edit_text("Пользователь не найден.")
            return

        first_name = user.get("first_name") or ""
        last_name = user.get("last_name") or ""
        name = (first_name + " " + (last_name or "")).strip() or "Без имени"
        username = user.get("username")
        balance = user.get("balance", 0)

        lines = [
            "Карточка пользователя 👤",
            "",
            f"ID: {uid}",
            f"Имя: {name}",
            f"Username: @{username}" if username else "Username: —",
            f"Баланс: {balance} токенов",
            "",
            "Начислить / списать токены:",
        ]

        kb = build_admin_user_keyboard(uid)
        context.user_data["admin_search_mode"] = False
        await query.message.edit_text("\n".join(lines), reply_markup=kb)
        return

    # Начисление токенов кнопками
    if data.startswith("admin_add|"):
        await query.answer()
        try:
            _, uid_str, amount_str = data.split("|", 2)
            uid = int(uid_str)
            amount = int(amount_str)
        except ValueError:
            return

        new_balance = await add_tokens(uid, amount)
        await log_admin_action(admin_id, uid, "admin_add_button", amount)

        await query.answer(
            f"Начислено {amount} токенов (баланс {new_balance})",
            show_alert=False,
        )

        # Уведомление пользователю
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    f"🎉 Ваш баланс пополнен на {amount} токенов.\n"
                    f"Текущий баланс: {new_balance} токенов.\n\n"
                    "Можете продолжать генерации в боте 🙂"
                ),
            )
        except Exception as e:
            logger.warning("Не удалось отправить уведомление пользователю %s: %s", uid, e)

        # Обновляем карточку
        user = await supabase_get_user(uid)
        if not user:
            await query.message.edit_text("Пользователь не найден.")
            return

        first_name = user.get("first_name") or ""
        last_name = user.get("last_name") or ""
        name = (first_name + " " + (last_name or "")).strip() or "Без имени"
        username = user.get("username")
        balance = user.get("balance", 0)

        lines = [
            "Карточка пользователя 👤",
            "",
            f"ID: {uid}",
            f"Имя: {name}",
            f"Username: @{username}" if username else "Username: —",
            f"Баланс: {balance} токенов",
            "",
            "Начислить / списать токены:",
        ]
        kb = build_admin_user_keyboard(uid)
        await query.message.edit_text("\n".join(lines), reply_markup=kb)
        return

    # Списание токенов кнопками
    if data.startswith("admin_sub|"):
        await query.answer()
        try:
            _, uid_str, amount_str = data.split("|", 2)
            uid = int(uid_str)
            amount = int(amount_str)
        except ValueError:
            return

        new_balance = await subtract_tokens(uid, amount)
        await log_admin_action(admin_id, uid, "admin_sub_button", -amount)

        await query.answer(
            f"Списано {amount} токенов (баланс {new_balance})",
            show_alert=False,
        )

        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    f"⚠️ С вашего баланса списано {amount} токенов.\n"
                    f"Текущий баланс: {new_balance} токенов."
                ),
            )
        except Exception as e:
            logger.warning("Не удалось отправить уведомление пользователю %s: %s", uid, e)

        user = await supabase_get_user(uid)
        if not user:
            await query.message.edit_text("Пользователь не найден.")
            return

        first_name = user.get("first_name") or ""
        last_name = user.get("last_name") or ""
        name = (first_name + " " + (last_name or "")).strip() or "Без имени"
        username = user.get("username")
        balance = user.get("balance", 0)

        lines = [
            "Карточка пользователя 👤",
            "",
            f"ID: {uid}",
            f"Имя: {name}",
            f"Username: @{username}" if username else "Username: —",
            f"Баланс: {balance} токенов",
            "",
            "Начислить / списать токены:",
        ]
        kb = build_admin_user_keyboard(uid)
        await query.message.edit_text("\n".join(lines), reply_markup=kb)
        return

    # Обнуление баланса
    if data.startswith("admin_zero|"):
        await query.answer()
        try:
            _, uid_str = data.split("|", 1)
            uid = int(uid_str)
        except ValueError:
            return

        await set_balance(uid, 0)
        await log_admin_action(admin_id, uid, "admin_zero_button", 0)
        new_balance = 0

        await query.answer("Баланс пользователя обнулён", show_alert=False)

        try:
            await context.bot.send_message(
                chat_id=uid,
                text="🧹 Ваш баланс был обнулён администратором.",
            )
        except Exception as e:
            logger.warning("Не удалось отправить уведомление пользователю %s: %s", uid, e)

        user = await supabase_get_user(uid)
        if not user:
            await query.message.edit_text("Пользователь не найден.")
            return

        first_name = user.get("first_name") or ""
        last_name = user.get("last_name") or ""
        name = (first_name + " " + (last_name or "")).strip() or "Без имени"
        username = user.get("username")

        lines = [
            "Карточка пользователя 👤",
            "",
            f"ID: {uid}",
            f"Имя: {name}",
            f"Username: @{username}" if username else "Username: —",
            f"Баланс: {new_balance} токенов",
            "",
            "Начислить / списать токены:",
        ]
        kb = build_admin_user_keyboard(uid)
        await query.message.edit_text("\n".join(lines), reply_markup=kb)
        return


# ----------------------------------------
# Reply-кнопки пользователя + режим поиска для админа
# ----------------------------------------
async def handle_reply_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id

    # Режим админского поиска
    if is_admin(user_id) and context.user_data.get("admin_search_mode"):
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


# ----------------------------------------
# Callback настроек генерации
# ----------------------------------------
async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    # Не трогаем admin_* callbacks — их обрабатывает admin_callback
    if (query.data or "").startswith("admin_"):
        return

    await query.answer()
    data = query.data or ""
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
        await query.message.edit_text(
            format_settings_text(settings, balance=balance),
            reply_markup=build_settings_keyboard(settings),
        )
        return


# ----------------------------------------
# Генерация через nano-banana
# ----------------------------------------
async def generate_with_nano_banana(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    image_urls: Optional[List[str]] = None,
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

        image_url: Optional[str] = None
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

        # Скачиваем файл и отправляем как binary (чтобы не словить 400 от Telegram)
        async with httpx.AsyncClient() as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            img_bytes = resp.content

        bio = BytesIO(img_bytes)
        bio.name = f"nano-banana.{settings['output_format']}"
        bio.seek(0)

        await update.message.reply_photo(photo=bio)
        logger.info("Image successfully sent to user")

        # Списываем токены только после успешной отправки
        if await deduct_tokens(user_id, TOKENS_PER_IMAGE):
            new_balance = await get_balance(user_id)
            await update.message.reply_text(
                f"Списано {TOKENS_PER_IMAGE} токенов. Новый баланс: {new_balance}."
            )
            # Логируем генерацию
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
    await register_user(update.effective_user)
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
# main
# ----------------------------------------
def main() -> None:
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Пользовательские команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("history", history_command))

    # Админ-команды
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("admin_help", admin_help_command))
    application.add_handler(CommandHandler("add_tokens", add_tokens_command))

    # CallbackQuery: сначала админка, потом настройки генерации
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(settings_callback))

    # Фото и текст
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_buttons)
    )

    application.run_polling()


if __name__ == "__main__":
    main()
