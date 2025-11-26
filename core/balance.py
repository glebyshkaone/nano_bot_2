import logging
from typing import Tuple
from config import MODEL_INFO
from .supabase import supabase_get_user, supabase_update_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# BALANCE MANAGEMENT
# ---------------------------------------------------------

async def get_balance(user_id: int) -> int:
    try:
        user = await supabase_get_user(user_id)
        if user and isinstance(user.get("balance"), int):
            return user["balance"]
    except:
        pass
    return 0


async def set_balance(user_id: int, val: int) -> None:
    await supabase_update_user(user_id, {"balance": val, "updated_at": "now()"})


async def add_tokens(user_id: int, amount: int) -> int:
    cur = await get_balance(user_id)
    new = max(0, cur + amount)
    await set_balance(user_id, new)
    return new


# ---------------------------------------------------------
# MODEL COST LOGIC
# ---------------------------------------------------------

def get_generation_cost_tokens(settings: dict) -> int:
    model_key = settings.get("model", "banana")
    model_info = MODEL_INFO[model_key]
    base = model_info["base_cost"]

    # PRO 4K = double cost
    if model_key == "banana_pro":
        if settings.get("resolution") == "4K":
            return base * 2

    return base


async def deduct_tokens(user_id: int, settings: dict) -> Tuple[bool, int, int]:
    cost = get_generation_cost_tokens(settings)
    cur = await get_balance(user_id)

    if cur < cost:
        return False, cost, cur

    new = cur - cost
    await set_balance(user_id, new)
    return True, cost, new
