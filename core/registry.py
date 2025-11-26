import logging
from typing import Optional

from telegram import User as TgUser

from config import ADMIN_IDS
from .supabase import supabase_get_user, supabase_insert_user, supabase_update_user

logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def register_user(tg_user: Optional[TgUser]) -> None:
    if not tg_user:
        return

    uid = tg_user.id
    username = tg_user.username
    first_name = tg_user.first_name
    last_name = tg_user.last_name

    try:
        existing = await supabase_get_user(uid)
        if existing:
            payload = {
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "updated_at": "now()",
            }
            await supabase_update_user(uid, payload)
        else:
            payload = {
                "id": uid,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "balance": 0,
            }
            await supabase_insert_user(payload)
    except Exception as e:
        logger.error("register_user error for %s: %s", uid, e)
