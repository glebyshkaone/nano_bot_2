import logging
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# Импортируем наши хендлеры
from handlers.text_handlers import (
    start_command,
    menu_command,
    help_command,
    balance_command,
    history_command,
    handle_reply_buttons,
)

from handlers.photo_handlers import handle_photo

from admin_panel.panel import (
    admin_command,
    admin_help_command,
    admin_callback,
)

from generation.settings import handle_settings_callback


logger = logging.getLogger(__name__)


def register_handlers(app):
    """Регистрирует все хендлеры в приложении Telegram Bot."""

    logger.info("Registering handlers...")

    # Команды пользователя
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("history", history_command))

    # Команды админа
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("admin_help", admin_help_command))

    # CallbackQuery — админка
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^admin_"))

    # CallbackQuery — настройки генерации
    app.add_handler(
        CallbackQueryHandler(
            handle_settings_callback,
            pattern=r"^(set|reset)\|"
        )
    )

    # Фото → в генерацию
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Любой текст → обработка кнопок/поиск/промт
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_reply_buttons
        )
    )

    logger.info("Handlers registered successfully")
