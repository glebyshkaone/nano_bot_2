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
    except Exception:
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
# MODELS CONFIG
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
        "base_cost": 150,  # 150 токенов (1K/2K), 300 токенов (4K)
        "pricing_text": "150 токенов (1K/2K), 300 токенов (4K)",
    },
    "flux_ultra": {
        "key": "flux_ultra",
        "label": "Flux 1.1 PRO Ultra",
        "emoji": "⚡",
        "replicate": "black-forest-labs/flux-1.1-pro-ultra",
        "base_cost": 80,  # ~0.12$ при x2 от себестоимости 0.06$
        "pricing_text": "80 токенов за изображение",
    },
    "remove_bg": {
        "key": "remove_bg",
        "label": "Remove BG",
        "emoji": "🪄",
        "replicate": "lucataco/remove-bg:95fcc2a26d3899cd6c2691c900465aaeff466285a65c14638cc5f36f34befaf1",
        "base_cost": 1,
        "pricing_text": "5 бесплатных в день, затем 1₽",
    },
}

# ---------------------------------------------------------
# UI SCHEMA FOR MODEL SETTINGS
# ---------------------------------------------------------

MODEL_SETTINGS_SCHEMA = {
    # ---------- NANO BANANA ----------
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

    # ---------- NANO BANANA PRO ----------
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

    # ---------- FLUX 1.1 PRO ULTRA ----------
    # здесь только то, что удобно выбирать по кнопкам.
    # seed / safety / strength будем задавать текстом.
    "flux_ultra": [
        {
            "key": "raw",
            "label": "Raw Mode",
            "options": ["false", "true"],
            "per_row": 2,
        },
        {
            "key": "aspect_ratio",
            "label": "Аспект",
            "options": [
                "21:9", "16:9", "3:2", "4:3", "5:4", "1:1",
                "4:5", "3:4", "2:3", "9:16", "9:21"
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

    # ---------- REMOVE BACKGROUND ----------
    "remove_bg": [],
}
