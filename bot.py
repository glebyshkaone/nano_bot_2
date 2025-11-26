from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# local imports
from config import TELEGRAM_BOT_TOKEN
from utils.logger import setup_logger

from handlers.router import (
    start_command,
    menu_command,
    help_command,
    balance_command,
    history_command,
    handle_reply_buttons,
)

from handlers.admin_handlers import (
    admin_main,
    admin_callback,
    add_tokens_command
)

from handlers.photo_handlers import handle_photo

from handlers.settings_handlers import settings_callback


def main():
    logger = setup_logger()

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    logger.info("Bot started")

    # User commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("history", history_command))

    # Admin commands
    application.add_handler(CommandHandler("admin", admin_main))
    application.add_handler(CommandHandler("add_tokens", add_tokens_command))

    # Callbacks (admin first)
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(settings_callback))

    # Messages
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_buttons))

    application.run_polling()


if __name__ == "__main__":
    main()
