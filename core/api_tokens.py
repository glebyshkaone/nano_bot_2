import datetime
import secrets
from typing import Optional

import httpx

from config import (
    SUPABASE_API_TOKENS_ENABLED,
    SUPABASE_REST_URL,
    SUPABASE_SERVICE_ROLE_KEY,
)

SUPABASE_HEADERS = (
    {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if SUPABASE_API_TOKENS_ENABLED
    else {}
)


def _generate_token(prefix: str = "ps_", length: int = 32) -> str:
    """Генерируем токен вида ps_xxx, который будем отдавать пользователю."""
    return prefix + secrets.token_urlsafe(length)


async def create_api_token_for_user(
    user_id: int,
    scope: str = "photoshop",
    ttl_days: int = 90,
) -> str:
    """
    Создаёт новый токен для пользователя в таблице api_tokens и возвращает его строкой.
    Старые токены НЕ отключаем (при желании можно сделать отдельную команду /ps_revoke).
    """
    if not SUPABASE_API_TOKENS_ENABLED:
        raise RuntimeError("Supabase API tokens are disabled (missing service role key or URL)")

    token = _generate_token()

    expires_at: Optional[str] = None
    if ttl_days is not None:
        expires_dt = datetime.datetime.utcnow() + datetime.timedelta(days=ttl_days)
        # формируем ISO-строку с Z на конце
        expires_at = expires_dt.replace(microsecond=0).isoformat() + "Z"

    payload = {
        "user_id": user_id,
        "token": token,
        "scope": scope,
    }
    if expires_at:
        payload["expires_at"] = expires_at

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{SUPABASE_REST_URL}/api_tokens",
            headers=SUPABASE_HEADERS,
            json=payload,
        )
        # если что-то пошло не так — пусть упадёт, чтобы мы увидели ошибку в логах
        resp.raise_for_status()

    return token
