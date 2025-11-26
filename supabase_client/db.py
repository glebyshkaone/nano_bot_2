# supabase_client/db.py

import os
import httpx
from typing import Optional, List, Dict

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("Supabase credentials missing: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")

BASE_URL = SUPABASE_URL.rstrip("/") + "/rest/v1"

HEADERS = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}

# -------------------------------
# USERS
# -------------------------------

async def ensure_user(tg_user) -> None:
    """Создаёт или обновляет пользователя."""
    if not tg_user:
        return

    payload = {
        "id": tg_user.id,
        "username": tg_user.username,
        "first_name": tg_user.first_name,
        "last_name": tg_user.last_name,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/telegram_users",
            headers=HEADERS,
            params={"id": f"eq.{tg_user.id}", "select": "id"},
        )

    exists = resp.json()
    if exists:
        # update
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{BASE_URL}/telegram_users",
                headers=HEADERS,
                params={"id": f"eq.{tg_user.id}"},
                json={"username": tg_user.username,
                      "first_name": tg_user.first_name,
                      "last_name": tg_user.last_name,
                      "updated_at": "now()"}
            )
    else:
        # insert
        payload["balance"] = 0
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{BASE_URL}/telegram_users",
                headers=HEADERS,
                json=[payload],
            )


async def get_user(user_id: int) -> Optional[Dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/telegram_users",
            headers=HEADERS,
            params={"id": f"eq.{user_id}", "select": "*"},
        )
    data = r.json()
    return data[0] if data else None


async def get_balance(user_id: int) -> int:
    user = await get_user(user_id)
    if user and isinstance(user.get("balance"), int):
        return user["balance"]
    return 0


async def set_balance(user_id: int, new_balance: int) -> int:
    async with httpx.AsyncClient() as client:
        await client.patch(
            f"{BASE_URL}/telegram_users",
            headers=HEADERS,
            params={"id": f"eq.{user_id}"},
            json={"balance": new_balance, "updated_at": "now()"},
        )
    return new_balance


async def change_balance(user_id: int, delta: int) -> int:
    current = await get_balance(user_id)
    new_balance = max(0, current + delta)
    await set_balance(user_id, new_balance)
    return new_balance


async def list_recent_users(limit: int = 20) -> List[Dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/telegram_users",
            headers=HEADERS,
            params={
                "select": "id,username,first_name,last_name,balance,created_at",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )
    return r.json()


async def search_users(query: str, limit: int = 20) -> List[Dict]:
    """Поиск по id или по имени/username."""
    query = query.strip()

    params = {"select": "*", "limit": str(limit)}

    if query.isdigit():
        params["id"] = f"eq.{query}"
    else:
        cleaned = query.lstrip("@")
        params["or"] = f"username.ilike.*{cleaned}*,first_name.ilike.*{cleaned}*,last_name.ilike.*{cleaned}*"

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/telegram_users",
            headers=HEADERS,
            params=params,
        )
    return r.json()

# -------------------------------
# GENERATION LOGGING
# -------------------------------

async def log_generation(
    user_id: int,
    model: str,
    prompt: str,
    image_url: str,
    tokens_spent: int,
    settings: Dict,
) -> None:
    payload = {
        "user_id": user_id,
        "model": model,
        "prompt": prompt,
        "image_url": image_url,
        "tokens_spent": tokens_spent,
        "aspect_ratio": settings.get("aspect_ratio"),
        "resolution": settings.get("resolution"),
        "output_format": settings.get("output_format"),
        "safety_filter_level": settings.get("safety_filter_level"),
    }

    async with httpx.AsyncClient() as client:
        await client.post(
            f"{BASE_URL}/generations",
            headers=HEADERS,
            json=[payload],
        )

# -------------------------------
# ADMIN LOGGING
# -------------------------------

async def log_admin_action(
    admin_id: int,
    target_user_id: int,
    action: str,
    amount: int,
    note: Optional[str] = None,
) -> None:
    payload = {
        "admin_id": admin_id,
        "target_user_id": target_user_id,
        "action": action,
        "amount": amount,
        "note": note,
    }

    async with httpx.AsyncClient() as client:
        await client.post(
            f"{BASE_URL}/admin_actions",
            headers=HEADERS,
            json=[payload],
        )

