# handlers/admin_handlers.py

from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_IDS
from admin_panel.panel import build_admin_user_list, build_admin_user_controls
from supabase_client.db import (
    list_recent_users,
    search_users,
    get_user,
    change_balance,
    set_balance,
    log_admin_action,
)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ---------- /admin ----------
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ У вас нет доступа к админ-панели.")
        return

    users = await list_recent_users(limit=20)
    kb = build_admin_user_list(users)

    context.user_data["admin_search_mode"] = False

    await update.message.reply_text(
        "👑 *Админ-панель nano-bot*\n\n"
        "Показаны последние пользователи. Выберите, чтобы изменить баланс.",
        parse_mode="Markdown",
        reply_markup=kb,
    )


# ---------- CallbackQuery админки ----------
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    admin_id = query.from_user.id
    if not is_admin(admin_id):
        await query.answer("Нет доступа", show_alert=True)
        return

    data = query.data
    await query.answer()

    # назад к списку
    if data == "admin_back_main":
        users = await list_recent_users(limit=20)
        kb = build_admin_user_list(users)
        context.user_data["admin_search_mode"] = False

        await query.message.edit_text(
            "👑 *Админ-панель nano-bot*\n\n"
            "Показаны последние пользователи. Выберите, чтобы изменить баланс.",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    # запрос поиска
    if data == "admin_search_prompt":
        context.user_data["admin_search_mode"] = True
        await query.message.edit_text(
            "🔎 Введите ID, username или часть имени для поиска.\n\n"
            "Например:\n"
            "`123456789`\n"
            "`@username`\n"
            "`gleb`",
            parse_mode="Markdown",
        )
        return

    # карточка пользователя
    if data.startswith("admin_user|"):
        _, uid_str = data.split("|", 1)
        try:
            uid = int(uid_str)
        except ValueError:
            return

        user = await get_user(uid)
        if not user:
            await query.message.edit_text("Пользователь не найден.")
            return

        first_name = user.get("first_name") or ""
        last_name = user.get("last_name") or ""
        name = (first_name + " " + (last_name or "")).strip() or "Без имени"
        username = user.get("username")
        balance = user.get("balance", 0)

        lines = [
            "👤 *Пользователь*",
            "",
            f"ID: `{uid}`",
            f"Имя: {name}",
            f"Username: @{username}" if username else "Username: —",
            f"Баланс: *{balance}* токенов",
            "",
            "Выберите действие:",
        ]

        kb = build_admin_user_controls(uid)
        context.user_data["admin_search_mode"] = False

        await query.message.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)
        return

    # начисление токенов
    if data.startswith("admin_add|"):
        _, uid_str, amount_str = data.split("|", 2)
        try:
            uid = int(uid_str)
            amount = int(amount_str)
        except ValueError:
            return

        new_balance = await change_balance(uid, amount)
        await log_admin_action(admin_id, uid, "add_tokens", amount)

        # уведомление юзеру
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    f"🎉 Ваш баланс пополнен на {amount} токенов.\n"
                    f"Текущий баланс: {new_balance} токенов."
                ),
            )
        except Exception:
            pass

        await query.message.reply_text(
            f"✅ Начислено {amount} токенов пользователю {uid}.\n"
            f"Новый баланс: {new_balance}."
        )
        return

    # списание токенов
    if data.startswith("admin_sub|"):
        _, uid_str, amount_str = data.split("|", 2)
        try:
            uid = int(uid_str)
            amount = int(amount_str)
        except ValueError:
            return

        new_balance = await change_balance(uid, -amount)
        await log_admin_action(admin_id, uid, "sub_tokens", -amount)

        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    f"⚠️ С вашего баланса списано {amount} токенов.\n"
                    f"Текущий баланс: {new_balance} токенов."
                ),
            )
        except Exception:
            pass

        await query.message.reply_text(
            f"✅ Списано {amount} токенов у пользователя {uid}.\n"
            f"Новый баланс: {new_balance}."
        )
        return

    # обнуление баланса
    if data.startswith("admin_zero|"):
        _, uid_str = data.split("|", 1)
        try:
            uid = int(uid_str)
        except ValueError:
            return

        await set_balance(uid, 0)
        await log_admin_action(admin_id, uid, "zero_balance", 0)

        try:
            await context.bot.send_message(
                chat_id=uid,
                text="🧹 Ваш баланс был обнулён администратором.",
            )
        except Exception:
            pass

        await query.message.reply_text(f"Баланс пользователя {uid} обнулён.")
        return


# ---------- текст для поиска (admin_search_mode) ----------
async def handle_admin_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Если админ включил режим поиска — обрабатываем текст как запрос."""
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    if not context.user_data.get("admin_search_mode"):
        return

    query_text = update.message.text.strip().lstrip("@")
    context.user_data["admin_search_mode"] = False

    users = await search_users(query_text, limit=20)
    if not users:
        await update.message.reply_text(f"По запросу «{query_text}» ничего не найдено.")
        return

    kb = build_admin_user_list(users)
    await update.message.reply_text(
        f"Результаты поиска по «{query_text}»:",
        reply_markup=kb,
    )

