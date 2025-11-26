import io
import logging
from typing import Dict, List, Tuple, Optional

import replicate

from config import REPLICATE_API_TOKEN, MODEL_INFO

logger = logging.getLogger(__name__)

# Инициализация клиента Replicate
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)


async def run_model(
    prompt: str,
    settings: Dict,
    image_urls: Optional[List[str]] = None,
) -> Tuple[str, bytes]:
    """
    Универсальный раннер моделей:
    - banana (google/nano-banana)
    - banana_pro (google/nano-banana-pro)
    - flux_ultra (black-forest-labs/flux-1.1-pro-ultra)

    Возвращает (image_url, image_bytes)
    """
    model_key = settings.get("model", "banana")
    if model_key not in MODEL_INFO:
        model_key = "banana"

    model_cfg = MODEL_INFO[model_key]
    model_id = model_cfg["replicate"]

    image_urls = image_urls or []

    logger.info("run_model: model=%s, prompt=%s", model_key, prompt[:200])

    # -------- BANANA ----------
    if model_key == "banana":
        payload = {
            "prompt": prompt,
            "image_input": image_urls,
            "aspect_ratio": settings.get("aspect_ratio", "match_input_image"),
            "output_format": settings.get("output_format", "jpg"),
        }

        output = replicate_client.run(
            model_id,
            input=payload,
        )

        # Новые модели nano-banana возвращают file-like объект
        image_url = output.url()
        image_bytes = output.read()
        return image_url, image_bytes

    # -------- BANANA PRO ----------
    if model_key == "banana_pro":
        payload = {
            "prompt": prompt,
            "image_input": image_urls,
            "aspect_ratio": settings.get("aspect_ratio", "match_input_image"),
            "resolution": settings.get("resolution", "2K"),
            "output_format": settings.get("output_format", "jpg"),
            "safety_filter_level": settings.get("safety_filter_level", "block_only_high"),
        }

        output = replicate_client.run(
            model_id,
            input=payload,
        )

        image_url = output.url()
        image_bytes = output.read()
        return image_url, image_bytes

    # -------- FLUX 1.1 PRO ULTRA ----------
    if model_key == "flux_ultra":
        # flux не поддерживает match_input_image, подменяем на 1:1 при необходимости
        ar = settings.get("aspect_ratio", "1:1")
        if ar == "match_input_image":
            ar = "1:1"

        raw_flag = str(settings.get("raw", "false")).lower() == "true"
        safety_tol = int(str(settings.get("safety_tolerance", "2")))
        img_strength = float(str(settings.get("image_prompt_strength", "0.1")))

        payload = {
            "prompt": prompt,
            "aspect_ratio": ar,
            "output_format": settings.get("output_format", "jpg"),
            "raw": raw_flag,
            "safety_tolerance": safety_tol,
            "image_prompt_strength": img_strength,
        }

        # image_prompt — одна картинка
        if image_urls:
            payload["image_prompt"] = image_urls[0]

        seed_val = str(settings.get("seed", "off"))
        if seed_val and seed_val != "off":
            try:
                payload["seed"] = int(seed_val)
            except ValueError:
                pass

        output = replicate_client.run(
            model_id,
            input=payload,
        )

        image_url = output.url()
        image_bytes = output.read()
        return image_url, image_bytes

    # fallback (если что-то пошло не так с model_key)
    raise ValueError(f"Unsupported model: {model_key}")
