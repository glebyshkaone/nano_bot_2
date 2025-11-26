import logging
from typing import Optional

from config import TOKENS_PER_IMAGE
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


async def deduct_tokens_for_image(user_id: int) -> bool:
    current = await get_balance(user_id)
    if current < TOKENS_PER_IMAGE:
        return False
    new_balance = current - TOKENS_PER_IMAGE
    await set_balance(user_id, new_balance)
    return True
