from typing import List, Dict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_admin_main_keyboard(users: List[Dict]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []

    for u in users:
        uid = u["id"]
        balance = u.get("balance", 0)
        first_name = u.get("first_name") or ""
        last_name = u.get("last_name") or ""
        name = (first_name + " " + (last_name or "")).strip() or "Без имени"
        label = f"{name} ({balance})"
        rows.append([InlineKeyboardButton(label, callback_data=f"admin_user|{uid}")])

    if not rows:
        rows = [[InlineKeyboardButton("Нет пользователей", callback_data="admin_none")]]

    rows.append([InlineKeyboardButton("🔎 Поиск", callback_data="admin_search_prompt")])

    return InlineKeyboardMarkup(rows)


def build_admin_user_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("+150", callback_data=f"admin_add|{uid}|150"),
                InlineKeyboardButton("+500", callback_data=f"admin_add|{uid}|500"),
                InlineKeyboardButton("+1000", callback_data=f"admin_add|{uid}|1000"),
            ],
            [
                InlineKeyboardButton("−150", callback_data=f"admin_sub|{uid}|150"),
                InlineKeyboardButton("−500", callback_data=f"admin_sub|{uid}|500"),
                InlineKeyboardButton("−1000", callback_data=f"admin_sub|{uid}|1000"),
            ],
            [
                InlineKeyboardButton("🧹 Обнулить", callback_data=f"admin_zero|{uid}"),
            ],
            [
                InlineKeyboardButton("⬅️ Назад к списку", callback_data="admin_back_main"),
            ],
        ]
    )
