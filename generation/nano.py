import logging
from io import BytesIO
from typing import Optional, List

import httpx
import replicate
from telegram import Update
from telegram.ext import ContextTypes

from generation.settings import get_user_settings, MODEL_CONFIG
from supabase_client.client import register_user, get_balance, deduct_tokens

logger = logging.getLogger(__name__)

# Соответствие ключа модели из настроек и slugs на Replicate
MODEL_SLUGS = {
    "nano": "google/nano-banana",
    "nano_pro": "google/nano-banana-pro",
}


async def generate_with_model(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    image_urls: Optional[List[str]] = None,
) -> None:
    """
    Универсальная генерация через nano / nano_pro в зависимости от настроек пользователя.
    - учитывает баланс (токены)
    - списывает токены после успешной отправки
    - поддерживает image_input (референсы)
    """

    await register_user(update.effective_user)

    if not update.message:
        return

    prompt = (prompt or "").strip()
    if not prompt:
        await update.message.reply_text("Отправь текстовый промт 🙏")
        return

    user_id = update.effective_user.id
    settings = get_user_settings(context)

    # модель и цена
    model_key = settings.get("model_key", "nano_pro")
    model_info = MODEL_CONFIG.get(model_key, MODEL_CONFIG["nano_pro"])
    model_slug = MODEL_SLUGS.get(model_key, MODEL_SLUGS["nano_pro"])
    price = model_info["price"]

    # проверяем баланс
    balance = await get_balance(user_id)
    if balance < price:
        await update.message.reply_text(
            f"Недостаточно токенов: на балансе {balance}, нужно {price}.\n\n"
            "Напишите @glebyshkaone, чтобы пополнить баланс."
        )
        return

    await update.message.reply_text("Генерирую картинку, подожди 5–20 секунд… ⚙️")

    input_payload = {
        "prompt": prompt,
        "aspect_ratio": settings["aspect_ratio"],
        "resolution": settings["resolution"],
        "output_format": settings["output_format"],
        "safety_filter_level": settings["safety_filter_level"],
    }
    if image_urls:
        # репликейт у nano-бананы принимает image_input
        input_payload["image_input"] = image_urls

    logger.info(
        "Model: %s | user=%s | prompt=%s | settings=%s | refs=%s",
        model_slug,
        user_id,
        prompt,
        settings,
        image_urls,
    )

    try:
        # ВАЖНО: replicate использует REPLICATE_API_TOKEN из env, как мы уже настроили
        output = replicate.run(model_slug, input=input_payload)
        logger.info("Raw output from Replicate: %r (type=%s)", output, type(output))

        image_url: Optional[str] = None
        if isinstance(output, list) and output:
            image_url = output[0]
        elif isinstance(output, str):
            image_url = output
        elif hasattr(output, "url"):
            val = output.url
            image_url = val() if callable(val) else val

        if not image_url:
            await update.message.reply_text(
                f"Не удалось получить URL изображения из ответа модели: {output!r}"
            )
            return

        # Качаем картинку и отправляем как бинарь — чтобы не ловить 400 от Telegram
        async with httpx.AsyncClient() as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            img_bytes = resp.content

        bio = BytesIO(img_bytes)
        bio.name = f"nano-banana.{settings['output_format']}"
        bio.seek(0)

        await update.message.reply_photo(photo=bio)
        logger.info("Image successfully sent to user")

        # Списываем токены ТОЛЬКО после успешной отправки
        if await deduct_tokens(user_id, price):
            new_balance = await get_balance(user_id)
            await update.message.reply_text(
                f"Списано {price} токенов. Новый баланс: {new_balance}."
            )
        else:
            await update.message.reply_text(
                "Изображение сгенерировано, но не удалось списать токены — обратитесь к администратору."
            )

    except Exception as e:
        logger.exception("Ошибка при генерации/отправке")
        await update.message.reply_text(
            f"Произошла ошибка при генерации: {e}\n"
            "Если ошибка повторяется — напишите @glebyshkaone."
        )
