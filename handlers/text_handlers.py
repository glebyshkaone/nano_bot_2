from typing import List, Dict, Optional

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import ContextTypes, filters

from config import TOKENS_PER_IMAGE, ADMIN_IDS
from generation.settings import (
    get_user_settings,
    format_settings_text,
    build_settings_keyboard,
)
from generation.nano import generate_with_model
from supabase_client.client import (
    get_balance,
    fetch_generations,
    search_users,
)

# пытаемся подобрать правильную функцию регистрации
try:
    from supabase_client.client import upsert_user_from_telegram as register_user
except ImportError:  # вдруг она называется иначе
    try:
        from supabase_client.client import register_user  # type: ignore
    except ImportError:
        # заглушка, чтобы код не падал, если в клиенте имя другое
        async def register_user(*_args, **_kwargs):
            return


# --- helpers ----------------------------------------------------


def build_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("🚀 Старт"), KeyboardButton("🎛 Меню")],
        [
            KeyboardButton("💰 Баланс"),
            KeyboardButton("📜 История"),
            KeyboardButton("ℹ Помощь"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# --- user commands ----------------------------------------------


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)

    user_id = update.effective_user.id
    settings = get_user_settings(context)
    balance = await get_balance(user_id)

    text = (
        "Привет! Я nano-bot 🤖\n\n"
        "Отправь мне текстовый промт — я сгенерирую картинку с помощью моделей "
        "google/nano-banana и nano-banana-pro на Replicate.\n\n"
        "Ты можешь:\n"
        "• Отправить только текст — будет текст-to-image\n"
        "• Отправить фото с подписью — фото станет референсом (image_input)\n\n"
        "Чтобы пополнить баланс, напиши @glebyshkaone."
    )

    await update.message.reply_text(text, reply_markup=build_reply_keyboard())
    await update.message.reply_text(
        format_settings_text(settings, balance=balance),
        reply_markup=build_settings_keyboard(settings),
    )


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
        f"• 1 изображение = {TOKENS_PER_IMAGE} токенов (для выбранной модели).\n"
        "• Пополнить баланс можно, написав @glebyshkaone.\n\n"
        "1. Нажми /menu или «🎛 Меню».\n"
        "2. Выбери модель и настройки генерации.\n"
        "3. Отправь промт (и, при желании, фото-референс).\n"
        "4. Если хватает токенов — я сгенерирую картинку.\n\n"
        "Команды:\n"
        "/balance — баланс\n"
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
        "Чтобы пополнить баланс, напишите @glebyshkaone.",
    )


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    user_id = update.effective_user.id

    gens = await fetch_generations(user_id, limit=5)

    if not gens:
        await update.message.reply_text("Пока нет сохранённой истории генераций.")
        return

    lines: List[str] = ["Ваши последние генерации (до 5):", ""]
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


# --- main text handler (buttons, search, prompts) ----------------

from admin_panel.panel import build_admin_main_keyboard  # внизу, чтобы избежать циклов
from supabase_client.client import search_users  # уже импортнули выше, но оставим для ясности


async def handle_reply_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатываем:
    - нажатия reply-кнопок
    - ввод строки поиска в админке
    - обычные текстовые промты
    """
    await register_user(update.effective_user)

    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    user_id = update.effective_user.id

    # --- режим поиска в админке ---
    if is_admin(user_id) and context.user_data.get("admin_search_mode"):
        context.user_data["admin_search_mode"] = False
        query = text.lstrip("@").strip()

        users = await search_users(query, limit=20)
        if not users:
            await message.reply_text(f"По запросу «{query}» пользователей не найдено.")
            return

        total = len(users)
        lines = [
            f"Результаты поиска по «{query}» (найдено {total}):",
            "",
            "Нажмите на пользователя, чтобы открыть карточку.",
        ]
        kb = build_admin_main_keyboard(users)
        await message.reply_text("\n".join(lines), reply_markup=kb)
        return

    # --- reply-кнопки пользователя ---
    if text == "🚀 Старт":
        await start_command(update, context)
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

    # --- обычный текст → промт для генерации ---
    if text.startswith("/"):
        # на всякий случай игнорируем неизвестные команды
        return

    prompt = text
    if not prompt:
        await message.reply_text("Отправь текстовый промт 🙏")
        return

    await generate_with_model(update, context, prompt, image_urls=None)
