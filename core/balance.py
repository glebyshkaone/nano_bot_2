import logging
from typing import Tuple

from config import MODEL_INFO
from .supabase import (
    supabase_get_user,
    supabase_update_user,
    supabase_update_balance_if_matches,
)

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
        logger.error("get_balance error: %s", e, exc_info=True)
        raise
    return 0


async def set_balance(user_id: int, val: int) -> None:
    try:
        await supabase_update_user(user_id, {"balance": val, "updated_at": "now()"})
    except Exception as e:
        logger.error("set_balance error: %s", e)


async def add_tokens(user_id: int, amount: int) -> int:
    """Плюсовать токены к балансу (покупки / админка)."""
    return await _change_balance(user_id, delta=amount)


async def subtract_tokens(user_id: int, amount: int) -> int:
    """
    Старая функция для админки: просто вычитает фиксированное число токенов.
    """
    if amount <= 0:
        return await get_balance(user_id)

    return await _change_balance(user_id, delta=-amount)


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


async def deduct_tokens(
    user_id: int, settings: dict, override_cost: int | None = None
) -> Tuple[bool, int, int]:
    """
    Списывает токены за одну генерацию по текущим настройкам.
    Возвращает:
      (успех, стоимость, новый_баланс_или_текущий_если_не_хватило)
    """
    cost = override_cost if override_cost is not None else get_generation_cost_tokens(settings)
    updated = await _change_balance(user_id, delta=-cost, allow_overdraft=False)
    if updated is None:
        current = await get_balance(user_id)
        return False, cost, current
    return True, cost, updated


async def _change_balance(
    user_id: int,
    delta: int,
    allow_overdraft: bool = True,
    attempts: int = 3,
) -> int | None:
    """
    Optimistic concurrency update for balance using conditional PATCH.
    Returns new balance, or None if overdraft not allowed and balance is insufficient.
    """
    if attempts <= 0:
        raise ValueError("attempts must be positive")

    for _ in range(attempts):
        current = await get_balance(user_id)
        new_balance = current + delta

        if not allow_overdraft and new_balance < 0:
            return None

        new_balance = max(0, new_balance)
        updated = await supabase_update_balance_if_matches(user_id, current, new_balance)
        if updated:
            return new_balance

        logger.warning(
            "Balance update race detected for user %s; retrying", user_id
        )

    raise RuntimeError(f"Failed to update balance for user {user_id} after retries")
