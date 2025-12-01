from typing import Optional, Dict, List
import httpx
import logging

from config import SUPABASE_REST_URL, SUPABASE_HEADERS_BASE

logger = logging.getLogger(__name__)

# --------- USERS ---------
async def supabase_get_user(user_id: int) -> Optional[Dict]:
    params = {
        "id": f"eq.{user_id}",
        "select": "id,username,first_name,last_name,balance,created_at,updated_at",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_REST_URL}/telegram_users",
            headers=SUPABASE_HEADERS_BASE,
            params=params,
            timeout=10.0,
        )
    resp.raise_for_status()
    data = resp.json()
    return data[0] if data else None


async def supabase_insert_user(payload: Dict) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_REST_URL}/telegram_users",
            headers=SUPABASE_HEADERS_BASE,
            params={"select": "id"},
            json=[payload],
            timeout=10.0,
        )
    resp.raise_for_status()


async def supabase_update_user(user_id: int, payload: Dict) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{SUPABASE_REST_URL}/telegram_users",
            headers=SUPABASE_HEADERS_BASE,
            params={"id": f"eq.{user_id}", "select": "id"},
            json=payload,
            timeout=10.0,
        )
    resp.raise_for_status()


async def supabase_update_balance_if_matches(
    user_id: int, expected_balance: int, new_balance: int
) -> bool:
    """
    Optimistic lock: update balance only if current value matches expected_balance.
    Returns True if the row was updated.
    """
    params = {
        "id": f"eq.{user_id}",
        "balance": f"eq.{expected_balance}",
        "select": "id,balance",
    }
    payload = {"balance": new_balance, "updated_at": "now()"}

    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{SUPABASE_REST_URL}/telegram_users",
            headers=SUPABASE_HEADERS_BASE,
            params=params,
            json=payload,
            timeout=10.0,
        )
    resp.raise_for_status()
    try:
        data = resp.json()
        return bool(data)
    except Exception:
        return False


async def supabase_fetch_recent_users(limit: int = 20) -> List[Dict]:
    params = {
        "select": "id,username,first_name,last_name,balance,created_at",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_REST_URL}/telegram_users",
            headers=SUPABASE_HEADERS_BASE,
            params=params,
            timeout=10.0,
        )
    resp.raise_for_status()
    return resp.json()


async def supabase_search_users(query: str, limit: int = 20) -> List[Dict]:
    params = {
        "select": "id,username,first_name,last_name,balance,created_at",
        "limit": str(limit),
    }

    if query.isdigit():
        params["id"] = f"eq.{int(query)}"
    else:
        q = query.strip()
        or_param = f"(username.ilike.*{q}*,first_name.ilike.*{q}*,last_name.ilike.*{q}*)"
        params["or"] = or_param

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_REST_URL}/telegram_users",
            headers=SUPABASE_HEADERS_BASE,
            params=params,
            timeout=10.0,
        )
    resp.raise_for_status()
    return resp.json()


# --------- ADMIN ACTIONS ---------
async def log_admin_action(
    admin_id: int,
    target_id: int,
    action: str,
    amount: int,
    note: Optional[str] = None,
) -> None:
    payload = {
        "admin_id": admin_id,
        "target_user_id": target_id,
        "action": action,
        "amount": amount,
        "note": note,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_REST_URL}/admin_actions",
            headers=SUPABASE_HEADERS_BASE,
            json=[payload],
            timeout=10.0,
        )
    if resp.status_code >= 300:
        logger.warning("Failed to log admin_action: %s %s", resp.status_code, resp.text)


# --------- GENERATIONS ---------
async def log_generation(
    user_id: int,
    prompt: str,
    image_url: str,
    settings: Dict,
    tokens_spent: int,
) -> None:
    model_key = settings.get("model", "banana")
    from config import MODEL_INFO  # локальный импорт, чтобы избежать циклов

    model_cfg = MODEL_INFO.get(model_key, MODEL_INFO.get("banana", {}))
    replicate_id = model_cfg.get("replicate", model_key)
    payload = {
        "user_id": user_id,
        "prompt": prompt,
        "image_url": image_url,
        "tokens_spent": tokens_spent,
        "model": replicate_id,
        "aspect_ratio": settings.get("aspect_ratio"),
        "resolution": settings.get("resolution"),
        "output_format": settings.get("output_format"),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_REST_URL}/generations",
            headers=SUPABASE_HEADERS_BASE,
            json=[payload],
            timeout=10.0,
        )
    if resp.status_code >= 300:
        logger.warning("Failed to log generation: %s %s", resp.status_code, resp.text)


async def count_generations_since(
    user_id: int,
    model: str,
    created_after_iso: str,
) -> Optional[int]:
    """Возвращает количество генераций по модели с указанной даты."""
    headers = {
        **SUPABASE_HEADERS_BASE,
        "Prefer": "count=exact",
    }
    params = {
        "user_id": f"eq.{user_id}",
        "model": f"eq.{model}",
        "created_at": f"gte.{created_after_iso}",
        "select": "id",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_REST_URL}/generations",
            headers=headers,
            params=params,
            timeout=10.0,
        )

    if resp.status_code >= 300:
        logger.warning(
            "Failed to count generations: %s %s", resp.status_code, resp.text
        )
        return None

    content_range = resp.headers.get("content-range") or resp.headers.get(
        "Content-Range"
    )
    if content_range and "/" in content_range:
        try:
            return int(content_range.split("/")[-1])
        except ValueError:
            pass

    try:
        data = resp.json()
        return len(data)
    except Exception:
        return None


async def fetch_generations(user_id: int, limit: int = 5) -> List[Dict]:
    params = {
        "select": "id,prompt,image_url,tokens_spent,created_at",
        "user_id": f"eq.{user_id}",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_REST_URL}/generations",
            headers=SUPABASE_HEADERS_BASE,
            params=params,
            timeout=10.0,
        )
    if resp.status_code >= 300:
        logger.warning("Failed to fetch generations: %s %s", resp.status_code, resp.text)
        return []
    return resp.json()
