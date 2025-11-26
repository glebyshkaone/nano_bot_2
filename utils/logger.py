import logging
import os


def setup_logger():
    """
    Глобальная конфигурация логирования для всего проекта.
    Вызывается один раз из bot.py
    """
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger = logging.getLogger("nano-bot")
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    logger.info("Logger initialized with level %s", log_level)

    return logger

