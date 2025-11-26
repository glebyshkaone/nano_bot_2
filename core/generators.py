from typing import Dict, Optional, List, Tuple
import logging
import replicate

from config import MODEL_INFO

logger = logging.getLogger(__name__)


async def run_model(
    prompt: str,
    settings: Dict,
    image_urls: Optional[List[str]] = None,
) -> Tuple[str, bytes]:
    """
    Вызывает модель (banana / banana_pro) через Replicate
    и возвращает (image_url, image_bytes).

    Для nano-banana / nano-banana-pro Replicate возвращает
    объект файла с методами .url() и .read().
    """

    # 1) выбираем модель
    model_key = settings.get("model", "banana")
    model_info = MODEL_INFO.get(model_key, MODEL_INFO["banana"])
    model_name = model_info["replicate"]

    logger.info("Using model %s for prompt: %s", model_name, prompt)

    # 2) собираем payload
    input_payload = {
        "prompt": prompt,
        "aspect_ratio": settings["aspect_ratio"],
        "resolution": settings["resolution"],
        "output_format": settings["output_format"],
        "safety_filter_level": settings["safety_filter_level"],
    }

    if image_urls:
        input_payload["image_input"] = image_urls

    # 3) вызов модели
    output = replicate.run(model_name, input=input_payload)
    logger.info("Raw output from Replicate: %r (%s)", output, type(output))

    image_url: Optional[str] = None
    image_bytes: Optional[bytes] = None

    # Официальный формат nano-banana: объект с .url() и .read()
    if hasattr(output, "url") and hasattr(output, "read"):
        url_val = output.url
        image_url = url_val() if callable(url_val) else url_val

        read_val = output.read
        image_bytes = read_val() if callable(read_val) else read_val

    elif isinstance(output, list) and output:
        image_url = output[0]
        raise RuntimeError(
            "Модель вернула список URL, а не объект файла. "
            "Обнови генератор, чтобы скачивать картинку по ссылке."
        )

    elif isinstance(output, str):
        image_url = output
        raise RuntimeError(
            "Модель вернула строку-URL, а не объект файла. "
            "Обнови генератор, чтобы скачивать картинку по ссылке."
        )

    if not image_url or image_bytes is None:
        raise RuntimeError(f"Не удалось извлечь файл из ответа модели: {output!r}")

    return image_url, image_bytes

    if not image_url or image_bytes is None:
        raise RuntimeError(f"Не удалось извлечь файл из ответа модели: {output!r}")

    return image_url, image_bytes
