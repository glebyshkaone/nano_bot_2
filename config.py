import os

# ----------------------------------------
# Telegram
# ----------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set")

# ----------------------------------------
# Replicate
# ----------------------------------------
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
if not REPLICATE_API_TOKEN:
    raise ValueError("REPLICATE_API_TOKEN not set")

# ----------------------------------------
# Supabase
# ----------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")

SUPABASE_REST_URL = SUPABASE_URL.rstrip("/") + "/rest/v1"
SUPABASE_HEADERS_BASE = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}

# ----------------------------------------
# Admins
# ----------------------------------------
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = []

if ADMIN_IDS_RAW:
    for part in ADMIN_IDS_RAW.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ADMIN_IDS.append(int(part))
        except ValueError:
            # Просто пропускаем кривой ID
            continue

# ----------------------------------------
# Tokens pricing
# ----------------------------------------
# Базовая стоимость — можешь менять при желании
TOKENS_PER_IMAGE = 150

# ----------------------------------------
# Logging level (опционально)
# ----------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
