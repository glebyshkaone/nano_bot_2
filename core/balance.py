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
    except Exception as e:
        logger.error("get_balance error: %s", e)
    return 0


async def set_balance(user_id: int, val: int) -> None:
    try:
        await supabase_update_user(user_id, {"balance": val, "updated_at": "now()"})
    except Exception as e:
        logger.error("set_balance error: %s", e)


async def add_tokens(user_id: int, amount: int) -> int:
    """Плюсовать токены к балансу (покупки / админка)."""
    current = await get_balance(user_id)
    new_balance = max(0, current + amount)
    await set_balance(user_id, new_balance)
    return new_balance


async def subtract_tokens(user_id: int, amount: int) -> int:
    """
    Старая функция для админки: просто вычитает фиксированное число токенов.
    """
    if amount <= 0:
        return await get_balance(user_id)

    current = await get_balance(user_id)
    new_balance = max(0, current - amount)
    await set_balance(user_id, new_balance)
    return new_balance


# ---------------------------------------------------------
# MODEL COST LOGIC
# ---------------------------------------------------------

def get_generation_cost_tokens(settings: dict) -> int:
    """
    Стоимость генерации в токенах по текущим настройкам.
    - Banana / Flux: base_cost из MODEL_INFO
    - Banana PRO 4K: base_cost * 2
    """
    model_key = settings.get("model", "banana")
    model_info = MODEL_INFO.get(model_key, MODEL_INFO["banana"])
    base_cost = model_info["base_cost"]

    # Спец-логика для PRO 4K
    if model_key == "banana_pro":
        if settings.get("resolution") == "4K":
            return base_cost * 2

    return base_cost


async def deduct_tokens(user_id: int, settings: dict) -> Tuple[bool, int, int]:
    """
    Списывает токены за одну генерацию по текущим настройкам.
    Возвращает:
      (успех, стоимость, новый_баланс_или_текущий_если_не_хватило)
    """
    cost = get_generation_cost_tokens(settings)
    current = await get_balance(user_id)

    if current < cost:
        return False, cost, current

    new_balance = current - cost
    await set_balance(user_id, new_balance)
    return True, cost, new_balance
