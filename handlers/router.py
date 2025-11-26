# handlers/router.py

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# --- user handlers ---
from handlers.user_handlers import (
    cmd_start,
    cmd_menu,
    cmd_help,
    cmd_balance,
    cmd_history,
    handle_text_message,
)

# --- photo handler ---
from handlers.photo_handlers import handle_photo

# --- admin handlers ---
from handlers.admin_handlers import (
    cmd_admin,
    admin_callback,
    handle_admin_search,
)

# --- settings handlers ---
from handlers.settings_handlers import handle_settings_callback


def setup_handlers(app: Application) -> None:
    """
    Подключает все команды, message-хендлеры и обработку callback'ов.
    Вызывается из bot.py после создания Application.
    """

    # ------------------------
    # USER COMMANDS
    # ------------------------
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("history", cmd_history))

    # ------------------------
    # ADMIN COMMAND
    # ------------------------
    app.add_handler(CommandHandler("admin", cmd_admin))

    # ------------------------
    # CALLBACKS
    # ВАЖНО: админские callback'и обрабатываем ПЕРВЫМИ
    # ------------------------
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))

    # callback'и настроек генерации
    app.add_handler(CallbackQueryHandler(handle_settings_callback, pattern="^(set|reset)\|"))

    # ------------------------
    # PHOTO HANDLER (референсы)
    # ------------------------
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # ------------------------
    # ADMIN SEARCH MODE (текст)
    # ------------------------
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_admin_search
        )
    )

    # ------------------------
    # GENERAL TEXT HANDLER (промты + кнопки)
    # ------------------------
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text_message
        )
    )
