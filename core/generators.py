from typing import Dict, Optional, List, Tuple
import logging
from io import BytesIO

import httpx
import replicate

logger = logging.getLogger(__name__)


async def run_nano_banana(
    prompt: str,
    settings: Dict,
    image_urls: Optional[List[str]] = None,
) -> Tuple[str, bytes]:
    """
    Вызывает модель и возвращает (image_url, image_bytes).
    Исключения наружу — пусть хендлер ловит.
    """
    logger.info("Prompt: %s", prompt)
    logger.info("Settings: %s", settings)
    logger.info("Image refs: %s", image_urls)

    input_payload = {
        "prompt": prompt,
        "aspect_ratio": settings["aspect_ratio"],
        "resolution": settings["resolution"],
        "output_format": settings["output_format"],
        "safety_filter_level": settings["safety_filter_level"],
    }
    if image_urls:
        input_payload["image_input"] = image_urls

    output = replicate.run("google/nano-banana-pro", input=input_payload)
    logger.info("Raw output from replicate.run: %r (type=%s)", output, type(output))

    image_url: Optional[str] = None
    if isinstance(output, list) and output:
        image_url = output[0]
    elif isinstance(output, str):
        image_url = output
    elif hasattr(output, "url"):
        val = output.url
        image_url = val() if callable(val) else val

    if not image_url:
        raise RuntimeError(f"Не удалось получить URL изображения из ответа модели: {output!r}")

    async with httpx.AsyncClient() as client:
        resp = await client.get(image_url)
        resp.raise_for_status()
        img_bytes = resp.content

    return image_url, img_bytes
