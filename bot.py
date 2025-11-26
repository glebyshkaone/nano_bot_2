from telegram.ext import ApplicationBuilder

from config import TELEGRAM_BOT_TOKEN
from utils.logger import setup_logger
from handlers.router import register_handlers


def main() -> None:
    logger = setup_logger()
    logger.info("Starting nano-bot...")

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Регистрируем все хендлеры в одном месте
    register_handlers(application)

    logger.info("Application is running (polling)")
    application.run_polling()


if __name__ == "__main__":
    main()
