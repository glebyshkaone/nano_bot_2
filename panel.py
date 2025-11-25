
# admin_panel/panel.py — визуальная админка nano-bot

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def build_admin_user_list(users):
    rows = []
    for u in users:
        uid = u.get("id")
        balance = u.get("balance", 0)
        name = (u.get("first_name") or "") + " " + (u.get("last_name") or "")
        name = name.strip() or "Без имени"
        label = f"{name} — {balance} токенов"
        rows.append([InlineKeyboardButton(label, callback_data=f"admin_user|{uid}")])
    rows.append([InlineKeyboardButton("🔎 Поиск", callback_data="admin_search_prompt")])
    return InlineKeyboardMarkup(rows)

def build_admin_user_controls(uid):
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
                InlineKeyboardButton("⬅️ Назад", callback_data="admin_back_main")
            ]
        ]
    )
