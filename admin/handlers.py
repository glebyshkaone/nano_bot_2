from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    Application,
)

from core.registry import register_user, is_admin
from core.balance import add_tokens, subtract_tokens, set_balance, get_balance
from core.supabase import (
    supabase_fetch_recent_users,
    supabase_get_user,
    log_admin_action,
)
from .views import build_admin_main_keyboard, build_admin_user_keyboard


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

    await update.message.reply_text(
        f"✅ Пользователю {target_id} начислено {amount} токенов.\n"
        f"Новый баланс: {new_balance}"
    )

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
        import logging
        logging.warning("Не удалось отправить уведомление пользователю %s: %s", target_id, e)


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
            import logging
            logging.warning("Не удалось отправить уведомление пользователю %s: %s", uid, e)

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
            import logging
            logging.warning("Не удалось отправить уведомление пользователю %s: %s", uid, e)

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
            import logging
            logging.warning("Не удалось отправить уведомление пользователю %s: %s", uid, e)

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


def register_admin_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("admin_help", admin_help_command))
    app.add_handler(CommandHandler("add_tokens", add_tokens_command))

    # Обязательно до settings_callback (pattern="^admin_")
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
