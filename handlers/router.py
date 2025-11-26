# handlers/router.py

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from handlers.user_handlers import (
    cmd_start,
    cmd_menu,
    cmd_help,
    cmd_balance,
    cmd_history,
    handle_text_message,
    handle_photo_message,
)
from handlers.admin_handlers import (
    cmd_admin,
    admin_callback,
    handle_admin_search,
)
from handlers.settings_handlers import handle_settings_callback


def setup_handlers(app: Application) -> None:
    # --- user commands ---
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("history", cmd_history))

    # --- admin command ---
    app.add_handler(CommandHandler("admin", cmd_admin))

    # --- callback'и: сначала admin, потом настройки ---
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(handle_settings_callback, pattern="^(set|reset)\|"))

    # --- фото (референсы) ---
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))

    # --- admin поиск (текст, когда включен режим поиска) ---
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_search))

    # --- остальные текстовые сообщения — промты/кнопки ---
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )

