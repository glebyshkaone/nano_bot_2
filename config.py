import os
from typing import List


# ---------------------------------------------------------
# ENV
# ---------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS: List[int] = []
if ADMIN_IDS_RAW:
    try:
        ADMIN_IDS = [int(x) for x in ADMIN_IDS_RAW.split(",") if x.strip()]
    except:
        pass

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set")

if not REPLICATE_API_TOKEN:
    raise ValueError("REPLICATE_API_TOKEN not set")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")

SUPABASE_REST_URL = SUPABASE_URL.rstrip("/") + "/rest/v1"
SUPABASE_HEADERS_BASE = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}

# ---------------------------------------------------------
# PARAMETRIC MODEL CONFIG — ALL MODELS HERE
# ---------------------------------------------------------

MODEL_INFO = {
    "banana": {
        "key": "banana",
        "label": "Nano Banana",
        "emoji": "🍌",
        "replicate": "google/nano-banana",
        "base_cost": 50,
        "pricing_text": "50 токенов за изображение",
    },
    "banana_pro": {
        "key": "banana_pro",
        "label": "Nano Banana PRO",
        "emoji": "💎",
        "replicate": "google/nano-banana-pro",
        "base_cost": 150,
        "pricing_text": "150 токенов (1K/2K), 300 токенов (4K)",
    },
    # Добавлять новые модели теперь легко — просто сюда:
    # "flux": {
    #     "key": "flux",
    #     "label": "Flux",
    #     "emoji": "⚡",
    #     "replicate": "myorg/flux-model",
    #     "base_cost": 40,
    #     "pricing_text": "40 токенов",
    # },
}

# ---------------------------------------------------------
# UI SCHEMA FOR MODEL SETTINGS
# ---------------------------------------------------------

MODEL_SETTINGS_SCHEMA = {
    "banana": [
        {
            "key": "aspect_ratio",
            "label": "Аспект",
            "options": [
                "match_input_image", "1:1", "2:3", "3:2",
                "3:4", "4:3", "4:5", "5:4",
                "9:16", "16:9", "21:9"
            ],
            "per_row": 3,
        },
        {
            "key": "output_format",
            "label": "Формат",
            "options": ["jpg", "png"],
            "per_row": 2,
        },
    ],

    "banana_pro": [
        {
            "key": "resolution",
            "label": "Разрешение",
            "options": ["1K", "2K", "4K"],
            "per_row": 3,
        },
        {
            "key": "aspect_ratio",
            "label": "Аспект",
            "options": [
                "match_input_image", "1:1", "2:3", "3:2",
                "3:4", "4:3", "4:5", "5:4",
                "9:16", "16:9", "21:9"
            ],
            "per_row": 3,
        },
        {
            "key": "output_format",
            "label": "Формат",
            "options": ["jpg", "png"],
            "per_row": 2,
        },
        {
            "key": "safety_filter_level",
            "label": "Фильтр",
            "options": [
                "block_low_and_above",
                "block_medium_and_above",
                "block_only_high",
            ],
            "per_row": 1,
        },
    ],
}
