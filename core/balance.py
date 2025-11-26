import logging
from typing import Tuple

from config import MODEL_INFO
from .supabase import supabase_get_user, supabase_update_user

logger = logging.getLogger(__name__)


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


async def deduct_tokens(user_id: int, settings: dict) -> Tuple[bool, int, int]:
    """
    Списывает токены по выбранной модели.
    Возвращает (успех, стоимость, новый баланс или текущий, если не хватило).
    """
    model_key = settings.get("model", "banana")
    model_info = MODEL_INFO.get(model_key, MODEL_INFO["banana"])
    cost = model_info["cost"]

    current = await get_balance(user_id)
    if current < cost:
        return False, cost, current

    new_balance = current - cost
    await set_balance(user_id, new_balance)
    return True, cost, new_balance
    
