import os
from typing import List

# ----------------------------------------
# Env
# ----------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS: List[int] = []
if ADMIN_IDS_RAW:
    try:
        ADMIN_IDS = [int(x) for x in ADMIN_IDS_RAW.split(",") if x.strip()]
    except ValueError:
        print(f"Failed to parse ADMIN_IDS={ADMIN_IDS_RAW!r}")

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

# ----------------------------------------
# Модели и базовая стоимость в токенах
# ----------------------------------------
# base_cost — стоимость в токенах для "обычного" режима.
# Для banana_pro 4K стоимость считается как base_cost * 2.
MODEL_INFO = {
    "banana": {
        "label": "Banana",
        "replicate": "google/nano-banana",
        "base_cost": 50,   # 50 токенов за генерацию
    },
    "banana_pro": {
        "label": "Banana PRO",
        "replicate": "google/nano-banana-pro",
        "base_cost": 150,  # 150 токенов за 1K/2K, 300 токенов за 4K
    },
}
