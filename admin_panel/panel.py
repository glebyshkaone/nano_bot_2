# admin_panel/panel.py
# Визуальная админка — кнопки, панели, интерфейс

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_admin_user_list(users):
    """
    Главный экран админ-панели:
    - список пользователей
    - кнопка поиска
    """
    rows = []

    for u in users:
        uid = u.get("id")
        balance = u.get("balance", 0)
        first_name = u.get("first_name") or ""
        last_name = u.get("last_name") or ""
        name = (first_name + " " + last_name).strip() or "Без имени"

        label = f"{name} — {balance} токенов"
        rows.append([
            InlineKeyboardButton(label, callback_data=f"admin_user|{uid}")
        ])

    # Кнопка поиска
    rows.append([
        InlineKeyboardButton("🔎 Поиск", callback_data="admin_search_prompt")
    ])

    return InlineKeyboardMarkup(rows)


def build_admin_user_controls(uid: int) -> InlineKeyboardMarkup:
    """
    Панель управления конкретным пользователем:
    +150, +500, +1000
    -150, -500, -1000
    Обнуление
    Назад
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("+150", callback_data=f"admin_add|{uid}|150"),
                InlineKeyboardButton("+500", callback_data=f"admin_add|{uid}|500"),
                InlineKeyboardButton("+1000", callback_data=f"admin_add|{uid}|1000"),
            ],
            [
                InlineKeyboardButton("-150", callback_data=f"admin_sub|{uid}|150"),
                InlineKeyboardButton("-500", callback_data=f"admin_sub|{uid}|500"),
                InlineKeyboardButton("-1000", callback_data=f"admin_sub|{uid}|1000"),
            ],
            [
                InlineKeyboardButton("🧹 Обнулить", callback_data=f"admin_zero|{uid}")
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="admin_back_main")
            ]
        ]
    )

