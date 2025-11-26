# handlers/photo_handlers.py
# Обрабатывает отправку фото + caption как референс к Nano/Nano Pro

from telegram import Update
from telegram.ext import ContextTypes

from handlers.user_handlers import _run_generation
from supabase_client.db import ensure_user


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Принимает фото пользователя, извлекает file_path и передает в генерацию.
    Prompt берется из caption. Если его нет — создается дефолтный prompt.
    """
    await ensure_user(update.effective_user)

    if not update.message or not update.message.photo:
        return

    # берём самое большое превью
    photo = update.message.photo[-1]

    # достаем URL файла (telegram CDN)
    file = await context.bot.get_file(photo.file_id)
    image_url = file.file_path

    # prompt
    caption = (update.message.caption or "").strip()
    if not caption:
        caption = "image-to-image generation"

    # передаем в общую функцию генерации
    await _run_generation(update, context, prompt=caption, image_refs=[image_url])

