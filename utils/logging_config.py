import logging

def setup_logging():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting nano-bot with Supabase storage + admin panel + history")
    return logger
