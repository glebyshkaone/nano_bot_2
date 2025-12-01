import datetime
import hashlib
import logging
import secrets
from typing import Optional

import httpx

from config import SUPABASE_REST_URL, SUPABASE_SERVICE_ROLE_KEY

logger = logging.getLogger(__name__)

SUPABASE_HEADERS = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}


def _generate_token(prefix: str = "ps_", length: int = 32) -> str:
    """Генерируем токен вида ps_xxx, который будем отдавать пользователю."""
    return prefix + secrets.token_urlsafe(length)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_api_token_for_user(
    user_id: int,
    scope: str = "photoshop",
    ttl_days: int = 90,
) -> str:
    """
    Создаёт новый токен для пользователя в таблице api_tokens и возвращает его строкой.
    Старые токены НЕ отключаем (при желании можно сделать отдельную команду /ps_revoke).
    """
    token = _generate_token()

    expires_at: Optional[str] = None
    if ttl_days is not None:
        expires_dt = datetime.datetime.utcnow() + datetime.timedelta(days=ttl_days)
        # формируем ISO-строку с Z на конце
        expires_at = expires_dt.replace(microsecond=0).isoformat() + "Z"

    hashed = _hash_token(token)
    token_prefix = token[:8]

    payload = {
        "user_id": user_id,
        "token_hash": hashed,
        "token_prefix": token_prefix,
        "scope": scope,
    }
    if expires_at:
        payload["expires_at"] = expires_at

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                f"{SUPABASE_REST_URL}/api_tokens",
                headers=SUPABASE_HEADERS,
                json=payload,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # fallback for legacy schema without token_hash/token_prefix
            logger.warning(
                "Falling back to legacy token storage: %s %s",
                exc.response.status_code,
                exc.response.text,
            )
            legacy_payload = {
                "user_id": user_id,
                "token": token,
                "scope": scope,
            }
            if expires_at:
                legacy_payload["expires_at"] = expires_at
            resp = await client.post(
                f"{SUPABASE_REST_URL}/api_tokens",
                headers=SUPABASE_HEADERS,
                json=legacy_payload,
            )
            resp.raise_for_status()

    return token
