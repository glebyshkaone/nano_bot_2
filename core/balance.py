import logging
from typing import Tuple

from config import MODEL_INFO
from .supabase import supabase_get_user, supabase_update_user

logger = logging.getLogger(__name__)


# ---------- Базовые операции с балансом ----------

async def get_balance(user_id: int) -> int:
    try:
        user = await supabase_get_user(user_id)
        if user and isinstance(user.get("balance"), int):
            return user["balance"]
    except Exception as e:
        logger.error("get_balance error: %s", e)
    return 0


async def set_balance(user_id: int, new_balance: int) -> None:
    try:
        await supabase_update_user(user_id, {"balance": new_balance, "updated_at": "now()"})
    except Exception as e:
        logger.error("set_balance error: %s", e)


async def add_tokens(user_id: int, amount: int) -> int:
    current = await get_balance(user_id)
    new_balance = max(0, current + amount)
    await set_balance(user_id, new_balance)
    return new_balance


async def subtract_tokens(user_id: int, amount: int) -> int:
    if amount <= 0:
        return await get_balance(user_id)
    current = await get_balance(user_id)
    new_balance = max(0, current - amount)
    await set_balance(user_id, new_balance)
    return new_balance


# ---------- Стоимость генерации в токенах ----------

def get_generation_cost_tokens(settings: dict) -> int:
    """
    Возвращает стоимость генерации в токенах по текущим настройкам.
    Логика:
    - banana: всегда base_cost (50 токенов).
    - banana_pro:
        - 1K/2K: base_cost (150 токенов)
        - 4K: base_cost * 2 (300 токенов)
    """
    model_key = settings.get("model", "banana")
    model_info = MODEL_INFO.get(model_key, MODEL_INFO["banana"])
    base_cost = model_info["base_cost"]

    if model_key == "banana_pro":
        resolution = settings.get("resolution", "2K")
        if resolution == "4K":
            return base_cost * 2  # 300 токенов за 4K

    return base_cost


async def deduct_tokens(user_id: int, settings: dict) -> Tuple[bool, int, int]:
    """
    Списывает токены по выбранной модели и разрешению.
    Возвращает (успех, стоимость_в_токенах, новый_баланс_или_текущий).
    """
    cost_tokens = get_generation_cost_tokens(settings)

    current = await get_balance(user_id)
    if current < cost_tokens:
        return False, cost_tokens, current

    new_balance = current - cost_tokens
    await set_balance(user_id, new_balance)
    return True, cost_tokens, new_balance

    new_balance = current - cost
    await set_balance(user_id, new_balance)
    return True, cost, new_balance
    
