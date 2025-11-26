import logging
from io import BytesIO
from typing import Optional, List, Dict

import httpx
import replicate
from telegram import Update
from telegram.ext import ContextTypes

from generation.settings import get_user_settings
from supabase_client.client import get_balance, deduct_tokens, log_generation

logger = logging.getLogger(__name__)

# Две модели:
# - nano_pro  -> google/nano-banana-pro (150 токенов)
# - nano_base -> google/nano-banana (50 токенов)
NANO_MODELS: Dict[str, Dict] = {
    "nano_pro": {
        "ref": "google/nano-banana-pro",
        "price": 150,
        "title": "Nano Banana PRO",
    },
    "nano_base": {
        "ref": "google/nano-banana",
        "price": 50,
        "title": "Nano Banana",
    },
}


async def generate_with_model(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    model_key: str,
    prompt: str,
    image_urls: Optional[List[str]] = None,
) -> None:
    """
    Общая функция генерации для обеих моделей.
    model_key:
      - "nano_pro"  -> google/nano-banana-pro (150 токенов)
      - "nano_base" -> google/nano-banana (50 токенов)
    Если прилетит неизвестный ключ — используем PRO по умолчанию.
    """

    if not update.message:
        return

    tg_user = update.effective_user
    if not tg_user:
        return

    user_id = tg_user.id

    # Определяем модель
    model_cfg = NANO_MODELS.get(model_key) or NANO_MODELS["nano_pro"]
    model_ref: str = model_cfg["ref"]
    price: int = model_cfg["price"]
    model_title: str = model_cfg["title"]

    # Баланс
    balance = await get_balance(user_id)
    if balance < price:
        await update.message.reply_text(
            f"Недостаточно токенов: на балансе {balance}, нужно {price}.\n\n"
            "Напишите @glebyshkaone, чтобы пополнить баланс."
        )
        return

    # Настройки из user_data (aspect_ratio, resolution и т.д.)
    settings = get_user_settings(context)

    logger.info(
        "User %s | model=%s (%s) | price=%s | prompt=%r | settings=%s | refs=%s",
        user_id,
        model_key,
        model_ref,
        price,
        prompt,
        settings,
        image_urls,
    )

    await update.message.reply_text(
        f"Генерирую картинку через {model_title}, подожди 5–20 секунд… ⚙️"
    )

    try:
        input_payload = {
            "prompt": prompt,
            "aspect_ratio": settings["aspect_ratio"],
            "resolution": settings["resolution"],
            "output_format": settings["output_format"],
            "safety_filter_level": settings["safety_filter_level"],
        }

        # Референсы (image_input)
        if image_urls:
            input_payload["image_input"] = image_urls

        # ВАЖНО: replicate.run работает синхронно, поэтому вызываем его через run_in_executor
        loop = context.application.loop
        output = await loop.run_in_executor(
            None,
            lambda: replicate.run(
                model_ref,
                input=input_payload,
            ),
        )

        logger.info(
            "Raw output from replicate.run (model=%s): %r (type=%s)",
            model_ref,
            output,
            type(output),
        )

        # Достаём URL
        image_url: Optional[str] = None
        if isinstance(output, list) and output:
            image_url = output[0]
        elif isinstance(output, str):
            image_url = output
        elif hasattr(output, "url"):
            val = getattr(output, "url")
            image_url = val() if callable(val) else val

        if not image_url:
            await update.message.reply_text(
                f"Не удалось получить URL изображения из ответа модели: {output!r}"
            )
            return

        # Качаем картинку и отправляем как файл
        async with httpx.AsyncClient() as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            img_bytes = resp.content

        bio = BytesIO(img_bytes)
        bio.name = f"{model_key}.{settings['output_format']}"
        bio.seek(0)

        await update.message.reply_photo(photo=bio)
        logger.info("Image successfully sent to user %s via %s", user_id, model_ref)

        # Списываем токены ПОСЛЕ успешной отправки
        success = await deduct_tokens(user_id, price)
        if success:
            new_balance = await get_balance(user_id)
            await update.message.reply_text(
                f"Списано {price} токенов. Новый баланс: {new_balance}."
            )
            # Логируем в Supabase
            await log_generation(
                user_id=user_id,
                prompt=prompt,
                image_url=image_url,
                settings=settings,
                tokens_spent=price,
            )
        else:
            await update.message.reply_text(
                "Изображение сгенерировано, но не удалось списать токены — обратитесь к администратору."
            )

    except Exception as e:
        logger.exception("Ошибка при генерации/отправке через %s", model_ref)
        await update.message.reply_text(
            f"Произошла ошибка при генерации: {e}\n"
            "Если ошибка повторяется — напишите @glebyshkaone."
        )
