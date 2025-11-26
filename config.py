import os

# -----------------------
# Telegram
# -----------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN")

# -----------------------
# Replicate
# -----------------------
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
if not REPLICATE_API_TOKEN:
    raise ValueError("Missing REPLICATE_API_TOKEN")

# Модели
MODEL_NANO = "google/nano-banana"
MODEL_NANO_PRO = "google/nano-banana-pro"

# Цены
NANO_PRICE = 50          # basic банана
NANO_PRO_PRICE = 150     # pro банана

# -----------------------
# Supabase
# -----------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("Missing Supabase credentials")

# -----------------------
# Admins
# -----------------------
ADMIN_IDS = []
if os.getenv("ADMIN_IDS"):
    try:
        ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS").split(",")]
    except:
        raise ValueError("Invalid ADMIN_IDS env")
