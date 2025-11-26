# generation/nano_pro.py
import replicate
from typing import Optional, List


MODEL_NAME = "google/nano-banana-pro"


async def generate_nano_pro(
    prompt: str,
    *,
    aspect_ratio: str,
    resolution: str,
    output_format: str,
    safety_filter_level: str,
    image_refs: Optional[List[str]] = None,
):
    """
    Генерация через nano-banana-pro (дороже и качественнее).
    Возвращает URL картинки.
    """

    try:
        input_data = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
            "safety_filter_level": safety_filter_level,
        }

        # Референсы
        if image_refs:
            input_data["image_input"] = image_refs

        output = replicate.run(
            MODEL_NAME,
            input=input_data,
        )

        # Replicate может вернуть list или string
        if isinstance(output, list) and output:
            return output[0]

        if isinstance(output, str):
            return output

        if hasattr(output, "url"):
            val = output.url
            return val() if callable(val) else val

        return None

    except Exception as e:
        raise RuntimeError(f"Nano Pro generation error: {e}")

