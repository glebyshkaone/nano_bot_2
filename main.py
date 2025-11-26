from telegram.ext import ApplicationBuilder

from config import TELEGRAM_BOT_TOKEN
from utils.logging_config import setup_logging
from user.handlers import register_user_handlers
from admin.handlers import register_admin_handlers


def main() -> None:
    setup_logging()
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Админские и пользовательские хендлеры
    register_admin_handlers(application)
    register_user_handlers(application)

    application.run_polling()


if __name__ == "__main__":
    main()
