import os
import re
import time
import random
import sqlite3
import csv
import io
import json
import asyncio
import logging
from datetime import datetime, timedelta
from vkbottle import API

# Импортируем компоненты vkbottle
from vkbottle import Bot, BaseMiddleware
from vkbottle.bot import Bot, BotLabeler, Message
from vkbottle_types.objects import MessagesMessageActionStatus  # Новый импорт
from vkbottle.dispatch.middlewares import BaseMiddleware

# ==============================
# Конфигурация и инициализация
# ==============================
OWNER_ID = 527055305  # Укажите ID владельца бота

# Глобальные переменные и словари
answered_message_id = None
help_cmid = None
alt_cmid = None
panel_messages = {}
user_last_messages = {}

# Путь к базе данных
DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')
CHECK_INTERVAL = 1

logging.basicConfig(level=logging.INFO)

# Токен бота и список администраторов
TOKEN = "vk1.a.5bWRa7wwHUl-VkHE7sbxa9huYX1cHxZLFeNOa7H7xeNW-GK5ZGngviGtjF4D2eFkeWtIqdJI00TXK-NU4SpznSRMck0pekmPd0JTvAFMGUDu0_q93XeonG0MSAXkV931iPFTr0F7Ilzka4PW9ArlYAQgH14XznPIeC3LvzjDj3JMhhD_ZOstbBtJRrdUkTvwtxWc7pNJ8uigTj4_Q-hQjA"
bot = Bot(token=TOKEN)
api = API(TOKEN)
vk_api = API(token="vk1.a.5bWRa7wwHUl-VkHE7sbxa9huYX1cHxZLFeNOa7H7xeNW-GK5ZGngviGtjF4D2eFkeWtIqdJI00TXK-NU4SpznSRMck0pekmPd0JTvAFMGUDu0_q93XeonG0MSAXkV931iPFTr0F7Ilzka4PW9ArlYAQgH14XznPIeC3LvzjDj3JMhhD_ZOstbBtJRrdUkTvwtxWc7pNJ8uigTj4_Q-hQjA")

ADMINS = [527055305]
CHAT_ID = 2  # ID беседы, куда будем отправлять уведомления


# Приоритет ролей (больше число – выше приоритет)
ROLE_PRIORITY = {
    "owner": 8,
    "spec": 7,
    "depspec": 6,
    "senadmin": 5,
    "admin": 4,
    "senmoder": 3,
    "moder": 2,
    "user": 1
}

# Инициализация бота и labeler
bot = Bot(TOKEN)
labeler = BotLabeler()

class ChatOnlyMiddleware(BaseMiddleware[Message]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    async def pre(self, *args, **kwargs):
        # Предполагается, что первым аргументом будет объект Message
        if args:
            message = args[0]
        else:
            message = kwargs.get("message")
        if not message:
            return True  # Если не удалось извлечь сообщение, не блокируем
        
        if message.peer_id < 2000000000:
            await message.answer("❌ Эта команда доступна только в беседах.")
            return False
        return True

# Регистрируем middleware как класс (без создания экземпляра)
bot.labeler.message_view.register_middleware(ChatOnlyMiddleware)

# Пути к базам
GLOBAL_DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')  # глобальная база (если нужна)
# Функция для получения пути к базе чата:
def get_db_name(chat_id: int) -> str:
    """
    Возвращает путь к базе данных для конкретного чата.
    Файл будет создан в папке "chats" с именем "chat_<chat_id>.db".
    """
    return os.path.join("chats", f"chat_{chat_id}.db")

# ==============================
# Инициализация базы данных
# ==============================

# Функция для получения пути к БД беседы
def get_db_name(chat_id: int) -> str:
    os.makedirs("chats", exist_ok=True)
    return os.path.join("chats", f"chat_{chat_id}.db")

# Обновление структуры БД (добавление таблицы мутов)
def update_chat_db(chat_id: int):
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    # Создаем таблицы, если их нет
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            role TEXT DEFAULT 'user',
            count_messages INTEGER DEFAULT 0,
            last_messages TEXT,
            ban INTEGER DEFAULT 0,
            warn INTEGER DEFAULT 0,
            mute INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            admin_id INTEGER,
            reason TEXT,
            ban_date TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mutes (
            user_id INTEGER PRIMARY KEY,
            admin_id INTEGER,
            end_time TEXT,
            reason TEXT
        )
    """)

    conn.commit()
    conn.close()

# Функция для получения информации о пользователе из таблицы users
def get_user_info(user_id: int, chat_id: int):
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    cursor.execute("SELECT role, count_messages, last_messages, ban, mute FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    
    conn.close()
    return result

# Функция для получения количества блокировок для пользователя
def get_user_ban_count(user_id: int, chat_id: int):
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM banned_users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    conn.close()
    return result[0] if result else 0

# Функция для проверки мьюта пользователя
def is_user_muted(user_id: int, chat_id: int):
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM mutes WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    conn.close()
    return result[0] > 0

# Функция для получения даты регистрации из ВКонтакте
async def get_registration_date(user_id: int):
    try:
        # Получаем информацию о пользователе через API ВКонтакте
        response = await vk_api.users.get(user_ids=[user_id], fields="registered")
        registration_timestamp = response[0].get("registered", 0)
        if registration_timestamp:
            registration_date = datetime.datetime.fromtimestamp(registration_timestamp)
            return registration_date.strftime("%d.%m.%Y")
    except Exception as e:
        print(f"Ошибка при получении даты регистрации: {e}")
    return "Неизвестно"

# Проверка, является ли вызывающий модератором или выше
async def check_user_role(message: Message):
    # Проверим роль пользователя
    user_info = get_user_info(message.from_id, message.peer_id)
    return user_info and user_info[0] in ["moderator", "administrator", "owner"]

async def extract_user_id_from_reply(message: Message):
    if message.reply_message:
        return message.reply_message.from_id
    return None

async def extract_user_id_from_target(message: Message, target: str = None):
    if message.reply_message:
        return message.reply_message.from_id  # Если ответ на сообщение, возвращаем ID пользователя

    if target:
        if target.startswith("[id"):
            return int(target.split("|")[0][3:])  # Упоминание пользователя в формате [id12345|Имя]

        if "vk.com" in target:  # Если ссылка на страницу
            username = target.split("/")[-1]

            if username.startswith("id"):  # Ссылка вида https://vk.com/id12345
                return int(username[2:])

            try:
                user_info = await bot.api.users.get(user_ids=username)  # Получаем ID по короткому имени
                if user_info:
                    return user_info[0].id
            except Exception:
                return None  # Ошибка получения ID

    return None  # Если target не передан или не удалось извлечь ID

# Функция для добавления пользователя в бан-лист
def add_banned_user(chat_id: int, banned_id: int, admin_id: int, reason: str):
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO banned_users (user_id, admin_id, reason, ban_date)
        VALUES (?, ?, ?, ?)
    """, (banned_id, admin_id, reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    
    conn.commit()
    conn.close()

# Функция для удаления пользователя из бан-листа
def remove_banned_user(chat_id: int, user_id: int):
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
    
    conn.commit()
    conn.close()

def get_db_name(chat_id: int) -> str:
    os.makedirs("chats", exist_ok=True)
    return os.path.join("chats", f"chat_{chat_id}.db")

def is_banned(chat_id: int, user_id: int) -> bool:
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT admin_id, ban_date FROM banned_users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result if result else None

def get_db_name(chat_id: int) -> str:
    """
    Возвращает путь к базе данных для беседы.
    Файл создаётся в папке "chats" с именем "chat_<chat_id>.db".
    """
    return os.path.join("chats", f"chat_{chat_id}.db")

def register_user(chat_id: int, user_id: int, role: str = 'user'):
    """
    Регистрирует пользователя в базе беседы, если его ещё нет.
    При регистрации устанавливается указанная роль и count_messages = 0.
    """
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO users (id, role, count_messages, last_messages, ban, warn, mute)
            VALUES (?, ?, 0, '', 0, 0, 0)
        """, (user_id, role))  # Роль передается как параметр
    conn.commit()
    conn.close()

def get_chat_user_role(chat_id: int, user_id: int) -> str:
    """
    Возвращает роль пользователя в беседе.
    Если запись отсутствует – возвращает "user".
    """
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "user"

def update_chat_user_role(chat_id: int, user_id: int, new_role: str):
    """
    Обновляет роль пользователя в беседе.
    """
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
    conn.commit()
    conn.close()

def get_chat_staff(chat_id: int) -> list:
    """
    Возвращает список пользователей, у которых роль не равна "user".
    Каждый элемент – кортеж (id, role).
    """
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT id, role FROM users WHERE role != 'user'")
    staff = cursor.fetchall()
    conn.close()
    return staff

# ==============================
# Функции для работы с участниками беседы через API
# ==============================
async def get_user_id_from_mention(mention: str) -> int:
    """
    Извлекает user_id из упоминания вида "[id12345|Name]", ссылки или числовой строки.
    """
    if mention.startswith("https://vk.com/"):
        if "/id" in mention:
            match = re.search(r"vk\.com/id(\d+)", mention)
            if match:
                return int(match.group(1))
        else:
            username = mention.split("https://vk.com/")[-1]
            if username:
                user_id = await get_vk_user_id_by_username(username)
                return user_id
    if "[id" in mention and "|" in mention:
        try:
            return int(mention.split("[id")[1].split("|")[0])
        except (IndexError, ValueError):
            return None
    if mention.isdigit():
        return int(mention)
    return None

async def get_vk_user_id_by_username(username: str) -> int:
    access_token = 'YOUR_VK_ACCESS_TOKEN'
    url = f'https://api.vk.com/method/users.get?user_ids={username}&access_token={access_token}&v=5.131'
    try:
        import requests
        response = requests.get(url).json()
        if 'response' in response and len(response['response']) > 0:
            return response['response'][0]['id']
    except Exception as e:
        print(f"Ошибка получения user_id по username: {e}")
    return None

async def resolve_user_id(arg: str, bot) -> int:
    if arg.isdigit():
        return int(arg)
    elif "vk.com" in arg:
        username = arg.split("/")[-1]
        user = await bot.api.users.get(user_ids=username)
        return user[0].id if user else None
    return None

async def get_user_name(user_id: int) -> str:
    try:
        user_info = await bot.api.users.get(user_ids=user_id)
        if user_info:
            user = user_info[0]
            return f"{user.first_name} {user.last_name}"
    except Exception:
        pass
    return f"id{user_id}"

# ==============================
# Приоритет ролей
# ==============================
ROLE_PRIORITY = {
    "owner": 8,
    "spec": 7,
    "depspec": 6,
    "senadmin": 5,
    "admin": 4,
    "senmoder": 3,
    "moder": 2,
    "user": 1
}


def get_chat_user_role(chat_id: int, user_id: int) -> str:
    """
    Возвращает роль пользователя в базе чата.
    Если пользователя нет – возвращает "user".
    """
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "user"

def update_chat_user_role(chat_id: int, user_id: int, new_role: str):
    """
    Обновляет роль пользователя в базе чата.
    Если пользователя нет – ничего не происходит.
    """
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
    conn.commit()
    conn.close()

def get_chat_staff(chat_id: int) -> list:
    """
    Возвращает список сотрудников из таблицы users чата.
    Сотрудниками считаются те, у кого роль не равна 'user'.
    """
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT id, role FROM users WHERE role != 'user'")
    staff = cursor.fetchall()
    conn.close()
    return staff

def get_user_role(user_id: int) -> str:
    # Если это владелец, возвращаем роль "owner"
    if user_id == OWNER_ID:
        return "owner"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result["role"] if result else "user"


# ==============================
# Декоратор для работы только в беседах
# ==============================
def only_chats(func):
    async def wrapper(message: Message, *args, **kwargs):
        if message.peer_id < 2000000000:
            await message.reply("Эта команда доступна только в беседах.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

# ==============================
# Работа с глобальной базой (database.db)
# ==============================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def add_column_if_not_exists(column_name: str, column_definition: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(users)")
    columns = cursor.fetchall()
    if not any(col[1] == column_name for col in columns):
        cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_definition}")
        conn.commit()
    conn.close()

def initialize_columns():
    add_column_if_not_exists("points", "INTEGER DEFAULT 0")
    add_column_if_not_exists("total_messages", "INTEGER DEFAULT 0")
    add_column_if_not_exists("last_message_time", "INTEGER DEFAULT 0")
    add_column_if_not_exists("last_reward_time", "INTEGER DEFAULT 0")
    add_column_if_not_exists("last_russian_roulette", "INTEGER DEFAULT 0")

def add_user(user_id: int) -> bool:
    """Регистрирует пользователя, если его ещё нет в таблице users."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone():
        conn.close()
        return False
    cursor.execute("INSERT INTO users (user_id, registration_date, role, balance, points, level) VALUES (?, ?, ?, ?, ?, ?)",
                   (user_id, datetime.now().strftime("%Y-%m-%d"), "user", 100, 0, 1))
    conn.commit()
    conn.close()
    return True

def get_user_role(user_id: int) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result["role"] if result else "user"

def update_user_role(user_id: int, new_role: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = ? WHERE user_id = ?", (new_role, user_id))
    conn.commit()
    conn.close()

def get_alll_nicknames():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT vk_id, nickname FROM nicknames")
        return cursor.fetchall()

def remove_nickname_from_db(vk_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM nicknames WHERE vk_id = ?", (vk_id,))
        conn.commit()

def remove_user(user_id: int):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()

def get_staff():
    """Возвращает список сотрудников с их ролями из глобальной базы."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, role FROM users WHERE role IN ('owner', 'depspec', 'senadmin', 'admin', 'senmoder', 'moder')")
        return cursor.fetchall()

def get_all_chats() -> list:
    """Возвращает список всех синхронизированных чатов (из таблицы chats)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM chats")
        rows = cursor.fetchall()
    return [row[0] for row in rows]


def update_chat_role(chat_id: int, user_id: int, role: str):
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO staff (user_id, role) VALUES (?, ?)", (user_id, role))
    conn.commit()
    conn.close()

def update_user_message_count(chat_id: int, user_id: int):
    """Обновляет счетчик сообщений пользователя в базе данных чата."""
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    # Получаем текущее время в нужном формате
    current_time = datetime.now().strftime("%d-%m-%Y %H-%M")

    # Обновляем счетчик сообщений и время последнего сообщения
    cursor.execute("""
        SELECT count_messages, last_messages FROM users WHERE id = ?
    """, (user_id,))
    
    result = cursor.fetchone()
    if result:
        count_messages, last_messages = result
        # Обновляем только счетчик и время последнего сообщения
        cursor.execute("""
            UPDATE users 
            SET count_messages = count_messages + 1, last_messages = ? 
            WHERE id = ?
        """, (current_time, user_id))
    else:
        # Если пользователя нет, добавляем его с начальным счетчиком
        cursor.execute("""
            INSERT INTO users (id, count_messages, last_messages)
            VALUES (?, 1, ?)
        """, (user_id, current_time))

    conn.commit()
    conn.close()

async def get_chat_name(chat_id: int) -> str:
    """Получает название беседы через API по chat_id (peer_id = 2000000000 + chat_id)."""
    try:
        chat_info = await bot.api.messages.get_conversations_by_id(peer_ids=2000000000 + chat_id)
        if chat_info.items:
            return chat_info.items[0].chat_settings.title
        else:
            return f"Чат {chat_id}"
    except Exception:
        return f"Чат {chat_id}"

# ==============================
# Функции для работы с упоминаниями и пользователями (одинаковые)
# ==============================
async def get_user_id_from_mention(mention: str) -> int:
    """
    Извлекает user_id из:
      - упоминания вида "[id12345|Name]"
      - ссылки вида "https://vk.com/id12345" или "https://vk.com/username"
      - числовой строки
    """
    if mention.startswith("https://vk.com/"):
        if "/id" in mention:
            match = re.search(r"vk\.com/id(\d+)", mention)
            if match:
                return int(match.group(1))
        else:
            username = mention.split("https://vk.com/")[-1]
            if username:
                user_id = await get_vk_user_id_by_username(username)
                return user_id
    if "[id" in mention and "|" in mention:
        try:
            return int(mention.split("[id")[1].split("|")[0])
        except (IndexError, ValueError):
            return None
    if mention.isdigit():
        return int(mention)
    return None

async def get_vk_user_id_by_username(username: str) -> int:
    access_token = 'YOUR_VK_ACCESS_TOKEN'
    url = f'https://api.vk.com/method/users.get?user_ids={username}&access_token={access_token}&v=5.131'
    try:
        import requests
        response = requests.get(url).json()
        if 'response' in response and len(response['response']) > 0:
            return response['response'][0]['id']
    except Exception as e:
        print(f"Ошибка получения user_id по username: {e}")
    return None

async def resolve_user_id(arg: str, bot) -> int:
    if arg.isdigit():
        return int(arg)
    elif "vk.com" in arg:
        username = arg.split("/")[-1]
        user = await bot.api.users.get(user_ids=username)
        return user[0].id if user else None
    return None

async def get_user_name(user_id: int) -> str:
    try:
        user_info = await bot.api.users.get(user_ids=user_id)
        if user_info:
            user = user_info[0]
            return f"{user.first_name} {user.last_name}"
    except Exception:
        pass
    return f"id{user_id}"

def extract_user_id(mention: str) -> int:
    match = re.search(r"\[id(\d+)\|", mention)
    return int(match.group(1)) if match else None

# ==============================
# Команды бота
# ==============================


# Функция для выдачи мута
async def mute_user(chat_id: int, user_id: int, admin_id: int, duration: int, reason: str):
    update_chat_db(chat_id)  # Убедимся, что БД обновлена
    end_time = datetime.now() + timedelta(minutes=duration)
    db_name = get_db_name(chat_id)

    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    cursor.execute("INSERT OR REPLACE INTO mutes (user_id, admin_id, end_time, reason) VALUES (?, ?, ?, ?)", 
                   (user_id, admin_id, end_time.strftime("%Y-%m-%d %H:%M:%S"), reason))
    
    cursor.execute("UPDATE users SET mute = 1 WHERE id = ?", (user_id,))
    
    conn.commit()
    conn.close()

    admin_name = await get_user_name(admin_id)

    # Уведомление о муте
    await bot.api.messages.send(
        peer_id=chat_id, 
        message=f"[id{admin_id}|{admin_name}] выдал-(а) блокировку чата [id{user_id}|пользователю] на {duration} минут.\n\n Причина: {reason}", 
        random_id=0
    )

    await asyncio.sleep(duration * 60)

    # По истечении времени мут снимается (без уведомления)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM mutes WHERE user_id = ?", (user_id,))
    cursor.execute("UPDATE users SET mute = 0 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


@bot.on.message(text="/mute <target> <duration> <reason>")
@bot.on.message(text="+mute <target> <duration> <reason>")
@bot.on.message(text="!mute <target> <duration> <reason>")
@bot.on.message(text="/мут <target> <duration> <reason>")
@bot.on.message(text="+мут <target> <duration> <reason>")
@bot.on.message(text="!мут <target> <duration> <reason>")
async def mute_with_target(message: Message, target: str, duration: str, reason: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["moder"]:
        await message.reply("Недостаточно прав.")
        return
    await process_mute(message, target, duration, reason)

@bot.on.message(text="/mute <duration> <reason>")
@bot.on.message(text="+mute <duration> <reason>")
@bot.on.message(text="!mute <duration> <reason>")
@bot.on.message(text="/мут <duration> <reason>")
@bot.on.message(text="+мут <duration> <reason>")
@bot.on.message(text="!мут <duration> <reason>")
async def mute_with_reply(message: Message, duration: str, reason: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["moder"]:
        await message.reply("Недостаточно прав.")
        return
    if not message.reply_message:
        await message.reply("Укажите пользователя!")
        return
    target_id = message.reply_message.from_id
    await process_mute(message, target_id, duration, reason)

async def process_mute(message: Message, target: str | int, duration: str, reason: str):
    chat_id = message.peer_id
    admin_id = message.from_id

    if isinstance(target, str):
        target_id = await extract_user_id_from_target(message, target)
    else:
        target_id = target

    if not target_id:
        await message.reply("Не удалось определить пользователя.")
        return

    try:
        duration = int(duration)
        if duration <= 0:
            raise ValueError
    except ValueError:
        await message.reply("Укажите время в минутах.")
        return

    await mute_user(chat_id, target_id, admin_id, duration, reason)


@bot.on.message(text="/unmute <target>")
@bot.on.message(text="+unmute <target>")
@bot.on.message(text="!unmute <target>")
@bot.on.message(text="/размут <target>")
@bot.on.message(text="+размут <target>")
@bot.on.message(text="!размут <target>")
@bot.on.message(text="/снятьмут <target>")
@bot.on.message(text="+снятьмут <target>")
@bot.on.message(text="!снятьмут <target>")
async def unmute_user_with_target(message: Message, target: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["moder"]:
        await message.reply("Недостаточно прав.")
        return
    await process_unmute(message, target)

@bot.on.message(text="/unmute")
@bot.on.message(text="+unmute")
@bot.on.message(text="!unmute")
@bot.on.message(text="/размут")
@bot.on.message(text="+размут")
@bot.on.message(text="!размут")
@bot.on.message(text="/снятьмут")
@bot.on.message(text="+снятьмут")
@bot.on.message(text="!снятьмут")
async def unmute_user_with_reply(message: Message):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["moder"]:
        await message.reply("Недостаточно прав.")
        return
    if not message.reply_message:
        await message.reply("Укажите пользователя!")
        return
    target_id = message.reply_message.from_id
    await process_unmute(message, target_id)

async def process_unmute(message: Message, target: str | int):
    chat_id = message.peer_id

    if isinstance(target, str):
        target_id = await extract_user_id_from_target(message, target)
    else:
        target_id = target

    if not target_id:
        await message.reply("Не удалось определить пользователя.")
        return

    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    # Проверяем, находится ли пользователь в муте
    cursor.execute("SELECT * FROM mutes WHERE user_id = ?", (target_id,))
    mute_entry = cursor.fetchone()

    if not mute_entry:
        conn.close()
        await message.reply("Этот пользователь не замучен!")
        return

    # Снимаем мут
    cursor.execute("DELETE FROM mutes WHERE user_id = ?", (target_id,))
    cursor.execute("UPDATE users SET mute = 0 WHERE id = ?", (target_id,))
    conn.commit()
    conn.close()

    admin_id = message.from_id
    admin_name = await get_user_name(admin_id)

    # Отправляем сообщение о снятии мута
    await message.reply(f"[https://vk.com/id{admin_id}|{admin_name}] размутил-(а) [id{target_id}|{await get_user_name(target_id)}].")



@bot.on.message(text="/ban <target> <reason>")
@bot.on.message(text="+ban <target> <reason>")
@bot.on.message(text="!ban <target> <reason>")
@bot.on.message(text="/бан <target> <reason>")
@bot.on.message(text="+бан <target> <reason>")
@bot.on.message(text="!бан <target> <reason>")
async def ban_user_with_target(message: Message, target: str, reason: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["senmoder"]:
        await message.reply("Недостаточно прав.")
        return
    await process_ban(message, target, reason)

@bot.on.message(text="/ban <reason>")
@bot.on.message(text="+ban <reason>")
@bot.on.message(text="!ban <reason>")
@bot.on.message(text="/бан <reason>")
@bot.on.message(text="+бан <reason>")
@bot.on.message(text="!бан <reason>")
async def ban_user_with_reply(message: Message, reason: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["senmoder"]:
        await message.reply("Недостаточно прав.")
        return
    if not message.reply_message:
        await message.reply("Укажите пользователя!")
        return
    target_id = message.reply_message.from_id
    await process_ban(message, target_id, reason)

async def process_ban(message: Message, target: str | int, reason: str):
    chat_id = message.peer_id
    admin_id = message.from_id

    if isinstance(target, str):
        target_id = await extract_user_id_from_target(message, target)
    else:
        target_id = target

    if not target_id:
        await message.reply("Не удалось определить пользователя.")
        return

    if is_banned(chat_id, target_id):
        await message.reply("Пользователь уже заблокирован!")
        return

    add_banned_user(chat_id, target_id, admin_id, reason)

    admin_id = message.from_id
    admin_name = await get_user_name(admin_id)

    try:
        await bot.api.messages.remove_chat_user(chat_id=chat_id - 2000000000, member_id=target_id)
        await message.reply(f"[https://vk.com/id{admin_id}|{admin_name}] заблокировал-(а) [id{target_id}|{await get_user_name(target_id)}].\nПричина: {reason}")
    except Exception as e:
        await message.reply(f"Ошибка при исключении пользователя из чата!")



@bot.on.message(text="/unban <target>")
@bot.on.message(text="+unban <target>")
@bot.on.message(text="!unban <target>")
@bot.on.message(text="/разбан <target>")
@bot.on.message(text="+разбан <target>")
@bot.on.message(text="!разбан <target>")
@bot.on.message(text="/снятьбан <target>")
@bot.on.message(text="+снятьбан <target>")
@bot.on.message(text="!снятьбан <target>")
async def unban_user_with_target(message: Message, target: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["senmoder"]:
        await message.reply("Недостаточно прав.")
        return
    await process_unban(message, target)

@bot.on.message(text="/unban")
@bot.on.message(text="+unban")
@bot.on.message(text="!unban")
@bot.on.message(text="/разбан")
@bot.on.message(text="+разбан")
@bot.on.message(text="!разбан")
@bot.on.message(text="/снятьбан")
@bot.on.message(text="+снятьбан")
@bot.on.message(text="!снятьбан")
async def unban_user_with_reply(message: Message):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["senmoder"]:
        await message.reply("Недостаточно прав.")
        return
    if not message.reply_message:
        await message.reply("Укажите пользователя!")
        return
    target_id = message.reply_message.from_id
    await process_unban(message, target_id)

async def process_unban(message: Message, target: str | int):
    chat_id = message.peer_id

    if isinstance(target, str):
        target_id = await extract_user_id_from_target(message, target)
    else:
        target_id = target

    if not target_id:
        await message.reply("Не удалось определить пользователя.")
        return

    if not is_banned(chat_id, target_id):
        await message.reply("Пользователь не заблокирован.")
        return
    
    admin_id = message.from_id
    admin_name = await get_user_name(admin_id)

    remove_banned_user(chat_id, target_id)
    await message.reply(f"[https://vk.com/id{admin_id}|{admin_name}] разблокировал-(а) [id{target_id}|{await get_user_name(target_id)}].")



# Функция для получения имени пользователя по ID
async def get_user_name(user_id: int) -> str:
    try:
        # Получаем информацию о пользователе с помощью API
        user_info = await bot.api.users.get(user_ids=user_id)
        user = user_info[0]
        return f"{user.first_name} {user.last_name}"
    except Exception:
        # Если не удалось получить имя, возвращаем ID пользователя
        return f"User {user_id}"

def register_user(chat_id: int, user_id: int, role: str = 'user'):
    """
    Регистрирует пользователя в базе беседы, если его ещё нет.
    При регистрации устанавливается указанная роль и count_messages = 0.
    """
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO users (id, role, count_messages, last_messages, ban, warn, mute)
            VALUES (?, ?, 0, '', 0, 0, 0)
        """, (user_id, role))  # Роль передается как параметр
    conn.commit()
    conn.close()

@bot.on.message(text="/sync")
@bot.on.message(text="+sync")
@bot.on.message(text="!sync")
@bot.on.message(text="/синхрон")
@bot.on.message(text="+синхрон")
@bot.on.message(text="!синхрон")
async def gsync(message: Message):
    chat_id = message.peer_id  # для беседы (peer_id >= 2000000000)
    update_chat_db(chat_id)  # Создаем базу данных для беседы

    try:
        # Получаем список участников беседы через API
        members_response = await bot.api.messages.get_conversation_members(peer_id=message.peer_id)
        
        # Получаем список участников из правильного атрибута
        members = members_response.items if hasattr(members_response, 'items') else []
        
        # Регистрация всех участников
        for member in members:
            # Проверяем, если это нужный пользователь (ID 527055305), то даем роль owner
            role = "owner" if member.member_id == 527055305 else "user"
            register_user(chat_id, member.member_id, role)  # Регистрируем с ролью

        await message.reply(f"Беседа успешно синхронизирована с базой данных!")

    except Exception as e:
        await message.reply(f"Ошибка при синхронизации: {e}")

@bot.on.message(text="/gban <target> <reason>")
@bot.on.message(text="+gban <target> <reason>")
@bot.on.message(text="!gban <target> <reason>")
@bot.on.message(text="/гбан <target> <reason>")
@bot.on.message(text="+гбан <target> <reason>")
@bot.on.message(text="!гбан <target> <reason>")
async def global_ban(message: Message, target: str, reason: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["senadmin"]:
        await message.reply("Недостаточно прав.")
        return
    admin_id = message.from_id
    admin_name = await get_user_name(admin_id)
    
    # Пробуем сначала получить ID из упоминания/ссылки
    target_id = await extract_user_id_from_target(message, target)
    
    if not target_id:
        await message.reply("Не удалось определить пользователя.")
        return

    # Добавляем пользователя в бан-лист во всех чатах
    chat_db_files = [f for f in os.listdir("chats") if f.endswith(".db")]
    
    for chat_db in chat_db_files:
        chat_id = int(chat_db.split("_")[1].split(".")[0])  # Получаем chat_id из имени файла
        db_name = get_db_name(chat_id)
        
        # Добавляем пользователя в бан-лист всех чатов
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO banned_users (user_id, admin_id, reason, ban_date) VALUES (?, ?, ?, ?)",
                       (target_id, admin_id, reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()

        # Получаем список всех участников чата
        members = await bot.api.messages.get_conversation_members(peer_id=chat_id)
        
        # Проверяем, есть ли целевой пользователь в чате
        if any(member.member_id == target_id for member in members.items):
            try:
                # Исключаем пользователя из чата
                await bot.api.messages.remove_chat_user(chat_id=chat_id - 2000000000, member_id=target_id)

                # Отправляем сообщение о блокировке в чат
                await bot.api.messages.send(
                    peer_id=chat_id,
                    message=(f"[https://vk.com/id{admin_id}|{admin_name}] заблокировал "
                             f"@id{target_id} ({await get_user_name(target_id)}) во всех беседах.\n"
                             f"Причина: {reason}"),
                    random_id=0
                )
            except Exception as e:
                print(f"Ошибка при кике из чата {chat_id} для пользователя {target_id}: {e}")
    
    await message.reply(f"Успешно!")


@bot.on.message(text="/gban <reason>")
@bot.on.message(text="+gban <reason>")
@bot.on.message(text="!gban <reason>")
@bot.on.message(text="/гбан <reason>")
@bot.on.message(text="+гбан <reason>")
@bot.on.message(text="!гбан <reason>")
async def global_ban_by_reply(message: Message, reason: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["senadmin"]:
        await message.reply("Недостаточно прав.")
        return
    admin_id = message.from_id
    admin_name = await get_user_name(admin_id)
    
    # Извлекаем ID из ответа на сообщение
    target_id = await extract_user_id_from_reply(message)
    
    if not target_id:
        await message.reply("Не удалось определить пользователя.")
        return

    # Добавляем пользователя в бан-лист во всех чатах
    chat_db_files = [f for f in os.listdir("chats") if f.endswith(".db")]
    
    for chat_db in chat_db_files:
        chat_id = int(chat_db.split("_")[1].split(".")[0])  # Получаем chat_id из имени файла
        db_name = get_db_name(chat_id)
        
        # Добавляем пользователя в бан-лист всех чатов
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO banned_users (user_id, admin_id, reason, ban_date) VALUES (?, ?, ?, ?)",
                       (target_id, admin_id, reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()

        # Получаем список всех участников чата
        members = await bot.api.messages.get_conversation_members(peer_id=chat_id)
        
        # Проверяем, есть ли целевой пользователь в чате
        if any(member.member_id == target_id for member in members.items):
            try:
                # Исключаем пользователя из чата
                await bot.api.messages.remove_chat_user(chat_id=chat_id - 2000000000, member_id=target_id)

                # Отправляем сообщение о блокировке в чат
                await bot.api.messages.send(
                    peer_id=chat_id,
                    message=(f"[https://vk.com/id{admin_id}|{admin_name}] заблокировал "
                             f"@id{target_id} ({await get_user_name(target_id)}) во всех беседах.\n"
                             f"Причина: {reason}"),
                    random_id=0
                )
            except Exception as e:
                print(f"Ошибка при кике из чата {chat_id} для пользователя {target_id}: {e}")
    
    await message.reply(f"Успешно!")


@bot.on.message(text="/gunban <target>")
@bot.on.message(text="+gunban <target>")
@bot.on.message(text="!gunban <target>")
async def global_unban_with_target(message: Message, target: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["senadmin"]:
        await message.reply("Недостаточно прав.")
        return
    await process_global_unban(message, target)

@bot.on.message(text="/gunban")
@bot.on.message(text="+gunban")
@bot.on.message(text="!gunban")
async def global_unban_with_reply(message: Message):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["senadmin"]:
        await message.reply("Недостаточно прав.")
        return
    if not message.reply_message:
        await message.reply("Укажите пользователя")
        return
    target_id = message.reply_message.from_id
    await process_global_unban(message, target_id)

async def process_global_unban(message: Message, target: str | int):
    admin_id = message.from_id

    if isinstance(target, str):
        target_id = await extract_user_id_from_target(message, target)
    else:
        target_id = target

    if not target_id:
        await message.reply("Не удалось определить пользователя.")
        return

    # Перебираем все базы данных чатов
    chat_db_files = [f for f in os.listdir("chats") if f.endswith(".db")]

    for chat_db in chat_db_files:
        chat_id = int(chat_db.split("_")[1].split(".")[0])  # Получаем chat_id из имени файла
        db_name = get_db_name(chat_id)

        # Подключаемся к БД и удаляем пользователя из таблицы банов
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (target_id,))
        conn.commit()
        conn.close()

    await message.reply(f"Пользователь [id{target_id}|{await get_user_name(target_id)}] был успешно разблокирован во всех беседах.")

@bot.on.message(text="/kick <arg>")
@bot.on.message(text="/кик <arg>")
@bot.on.message(text="/исключить <arg>")
@bot.on.message(text="/выкинуть <arg>")
@bot.on.message(text="/убрать <arg>")
@bot.on.message(text="!kick <arg>")
@bot.on.message(text="!кик <arg>")
@bot.on.message(text="!исключить <arg>")
@bot.on.message(text="!выкинуть <arg>")
@bot.on.message(text="!убрать <arg>")
@bot.on.message(text="+kick <arg>")
@bot.on.message(text="+кик <arg>")
@bot.on.message(text="+исключить <arg>")
@bot.on.message(text="+выкинуть <arg>")
@bot.on.message(text="+убрать <arg>")
async def kick_handler(message, arg: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["moder"]:
        await message.reply("Недостаточно прав.")
        return
    # Извлекаем ID пользователя и причину
    parts = arg.split(" ", 1)
    uid = await get_user_id_from_mention(parts[0])
    if not uid:
        await message.reply("Не удалось извлечь идентификатор пользователя.")
        return

    reason = parts[1] if len(parts) > 1 else "не указана."  # Если причина есть, то берем, если нет — по умолчанию

    chat_id = message.chat_id  # текущая беседа
    admin_id = message.from_id
    admin_name = await get_user_name(admin_id)
    user_name = await get_user_name(uid)

    try:
        # Исключаем пользователя из беседы
        await bot.api.messages.remove_chat_user(chat_id=chat_id, member_id=uid)
        # Отправляем сообщение с причиной кика
        await message.reply(f"[https://vk.com/id{admin_id}|{admin_name}] исключил-(а) "
                            f"[https://vk.com/id{uid}|{user_name}] из беседы. \n\nПричина: {reason}")
    except Exception as e:
        await message.reply(f"Ошибка при исключении пользователя: {e}")

@bot.on.message(text="/kick")
@bot.on.message(text="/кик")
@bot.on.message(text="/исключить")
@bot.on.message(text="/выкинуть")
@bot.on.message(text="/убрать")
@bot.on.message(text="!kick")
@bot.on.message(text="!кик")
@bot.on.message(text="!исключить")
@bot.on.message(text="!выкинуть")
@bot.on.message(text="!убрать")
@bot.on.message(text="+kick")
@bot.on.message(text="+кик")
@bot.on.message(text="+исключить")
@bot.on.message(text="+выкинуть")
@bot.on.message(text="+убрать")
async def kick_reply_handler(message):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["moder"]:
        await message.reply("Недостаточно прав.")
        return
    if message.reply_message:
        # Получаем ID пользователя и причину
        uid = message.reply_message.from_id
        parts = message.text.split(" ", 1)
        reason = parts[1] if len(parts) > 1 else "не указана."  # Если причина есть, то берем, если нет — по умолчанию

        chat_id = message.chat_id
        admin_id = message.from_id
        admin_name = await get_user_name(admin_id)
        user_name = await get_user_name(uid)

        try:
            # Исключаем пользователя из беседы
            await bot.api.messages.remove_chat_user(chat_id=chat_id, member_id=uid)
            # Отправляем сообщение с причиной кика
            await message.reply(f"[https://vk.com/id{admin_id}|{admin_name}] исключил-(а) "
                                f"[https://vk.com/id{uid}|{user_name}] из беседы. \n\nПричина: {reason}")
        except Exception as e:
            await message.reply(f"Ошибка при исключении пользователя: {e}")
    else:
        await message.reply("Вы не указали пользователя")

# ----- Команда вывода списка сотрудников (staff) (работает только в беседах) -----
@bot.on.message(text=["/staff", "!staff", "+staff", "/стафф", "!стафф", "+стафф"])
async def staff_handler(message: Message):
    # Проверяем, что команда вызвана в беседе
    if message.peer_id < 2000000000:
        await message.reply("Эта команда доступна только в беседах.")
        return
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    # Для вывода списка сотрудников допускаем минимальную роль "moder"
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["moder"]:
        await message.reply("Недостаточно прав.")
        return
    staff = get_chat_staff(chat_id)
    if not staff:
        await message.reply("Список сотрудников пуст.")
        return
    staff_text = "Владелец беседы - [club228029813|SURGUT MANAGER]\n"
    roles = {
        "owner": "Спец.администраторы",
        "depspec": "Зам.Спец администратора",
        "senadmin": "Старшие администраторы",
        "admin": "Администраторы",
        "senmoder": "Старшие модераторы",
        "moder": "Модераторы"
    }
    for role, description in roles.items():
        role_users = [
            f"[https://vk.com/id{user_id}|{await get_user_name(user_id)}]"
            for user_id, user_role in staff if user_role == role
        ]
        staff_text += f"\n{description}:\n"
        if role_users:
            staff_text += "\n".join(role_users) + "\n"
        else:
            staff_text += "Отсутствуют\n"
    await message.reply(staff_text.strip())



# Примеры команд для изменения ролей (все обновляют данные в базе чата)
@bot.on.message(text=["/addsenmoder <mention>", "+addsenmoder <mention>", "!addsenmoder <mention>", "+smod <mention>"])
async def addmoder_handler(message: Message, mention: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["senmoder"]:
        await message.reply("Недостаточно прав.")
        return
    target_id = await get_user_id_from_mention(mention)
    if not target_id:
        await message.reply("Не удалось определить пользователя по упоминанию.")
        return
    update_chat_user_role(chat_id, target_id, "moder")
    admin_name = await get_user_name(message.from_id)
    target_name = await get_user_name(target_id)
    await message.reply(f"[https://vk.com/id{message.from_id}|{admin_name}] выдал(а) права модератора [https://vk.com/id{target_id}|{target_name}].")

# Примеры команд для изменения ролей (все обновляют данные в базе чата)
@bot.on.message(text=["/addmoder <mention>", "+addmoder <mention>", "!addmoder <mention>", "+mod <mention>"])
async def addmoder_handler(message: Message, mention: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["admin"]:
        await message.reply("Недостаточно прав.")
        return
    target_id = await get_user_id_from_mention(mention)
    if not target_id:
        await message.reply("Не удалось определить пользователя по упоминанию.")
        return
    update_chat_user_role(chat_id, target_id, "senmoder")
    admin_name = await get_user_name(message.from_id)
    target_name = await get_user_name(target_id)
    await message.reply(f"[https://vk.com/id{message.from_id}|{admin_name}] выдал(а) права старшего модератора [https://vk.com/id{target_id}|{target_name}].")

@bot.on.message(text=["/addadmin <mention>", "+addadmin <mention>", "!addadmin <mention>"])
async def addadmin_handler(message: Message, mention: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["senadmin"]:
        await message.reply("Недостаточно прав.")
        return
    target_id = await get_user_id_from_mention(mention)
    if not target_id:
        await message.reply("Не удалось определить пользователя по упоминанию.")
        return
    update_chat_user_role(chat_id, target_id, "admin")
    admin_name = await get_user_name(message.from_id)
    target_name = await get_user_name(target_id)
    await message.reply(f"[https://vk.com/id{message.from_id}|{admin_name}] выдал(а) права администратора [https://vk.com/id{target_id}|{target_name}].")

# Пример команды снятия роли (возвращает роль "user")
@bot.on.message(text=["/removerole <mention>", "+removerole <mention>", "!removerole <mention>", "!rrole <mention>", "+rrole <mention>", "/rrole <mention>"])
async def remove_role_handler(message: Message, mention: str):
    chat_id = message.peer_id
    sender_id = message.from_id
    sender_role = get_chat_user_role(chat_id, sender_id)
    if mention:
        target_id = await get_user_id_from_mention(mention)
    elif message.reply_message:
        target_id = message.reply_message.from_id
    else:
        await message.reply("Вы не указали пользователя")
        return
    if not target_id:
        await message.reply("Не удалось определить пользователя по указанному аргументу.")
        return
    target_role = get_chat_user_role(chat_id, target_id)
    if ROLE_PRIORITY.get(sender_role, 0) <= ROLE_PRIORITY.get(target_role, 0):
        await message.reply("Недостаточно прав.")
        return
    update_chat_user_role(chat_id, target_id, "user")
    sender_name = await get_user_name(sender_id)
    target_name = await get_user_name(target_id)
    await message.reply(f"[https://vk.com/id{sender_id}|{sender_name}] забрал(а) роль у [https://vk.com/id{target_id}|{target_name}].")

# Пример команды для установки ника (работает с глобной таблицей nicknames в глобальной БД)
@bot.on.message(text=["/setnick <mention> <nickname>", "+setnick <mention> <nickname>", "!setnick <mention> <nickname>"])
async def set_nick(message: Message, mention: str, nickname: str):
    target_id = await get_user_id_from_mention(mention)
    if not target_id:
        await message.reply("❌ Не удалось определить пользователя.")
        return
    # Здесь можно работать с глобальной базой nicknames (не затрагиваем базу чата)
    conn = sqlite3.connect(GLOBAL_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nicknames (
            vk_id INTEGER PRIMARY KEY,
            nickname TEXT
        )
    """)
    cursor.execute("""
        INSERT INTO nicknames (vk_id, nickname) 
        VALUES (?, ?)
        ON CONFLICT(vk_id) DO UPDATE SET nickname = ?
    """, (target_id, nickname, nickname))
    conn.commit()
    conn.close()
    admin_name = await get_user_name(message.from_id)
    target_name = await get_user_name(target_id)
    await message.reply(f"[https://vk.com/id{message.from_id}|{admin_name}] установил(а) никнейм {nickname} пользователю [https://vk.com/id{target_id}|{target_name}].")

# ----- Команды для заместителя спец. администратора (depspec) -----
@bot.on.message(text=[
    "/addzsa", "/зса", "/zsa", "/addzsa",
    "+zsa", "+зса", "+addzsa",
    "!zsa", "!зса", "!addzsa"
])
async def addzsa_no_argument(message: Message):
    sender_role = get_user_role(message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["owner"]:
        await message.reply("Недостаточно прав.")
        return
    await message.reply("Вы не указали пользователя.")

@bot.on.message(text=[
    "/addzsa <mention>", "/зса <mention>", "/zsa <mention>", "/addzsa <mention>",
    "+zsa <mention>", "+зса <mention>", "+addzsa <mention>",
    "!zsa <mention>", "!зса <mention>", "!addzsa <mention>"
])
async def add_deputyspec_handler(message: Message, mention: str):
    chat_id = message.peer_id
    sender_role = get_chat_user_role(chat_id, message.from_id)
    if ROLE_PRIORITY.get(sender_role, 0) < ROLE_PRIORITY["owner"]:
        await message.reply("Недостаточно прав.")
        return
    target_id = await get_user_id_from_mention(mention)
    if not target_id:
        await message.reply("Не удалось определить пользователя по упоминанию.")
        return
    # Обновляем глобальную роль
    update_chat_user_role(chat_id, target_id, "depspec")
    # Обновляем роль во всех синхронизированных беседах
    chats = get_all_chats()
    for chat_id in chats:
        try:
            update_chat_role(chat_id, target_id, "depspec")
        except Exception as e:
            print(f"Ошибка обновления роли в чате {chat_id} для пользователя {target_id}: {e}")
    admin_name = await get_user_name(message.from_id)
    target_name = await get_user_name(target_id)
    await message.reply(f"[https://vk.com/id{message.from_id}|{admin_name}] выдал-(а) права заместителя спец.администратора [https://vk.com/id{target_id}|{target_name}].")


# Обработчик команды /help
@bot.on.message(text=["/help", "+help", "!help", "/хелп", "!хелп", "+хелп", "/помощь", "+помощь", "!помощь"])
async def help_handler(message: Message):
    global help_cmid
    logging.info(f"Получена команда /help от пользователя {message.from_id}")
    user_id = message.from_id
    chat_id = message.peer_id

    # Получаем роль пользователя из базы данных
    user_role = get_chat_user_role(chat_id, user_id)

    # Базовые команды, доступные всем пользователям
    help_text = """
Команды пользователей:    
/info — ресурсы сервера
/stats — посмотреть свою статистику
/getid — узнать оригинальную ссылку пользователя
/bug — сообщить разработчику о баге
    """

    # Определяем команды по ролям
    role_commands = {
        "moder": """
Команды модератора:
/staff — участники с ролями
/clear — очистить сообщение
/gnick — проверить никнейм пользователя
/kick — исключить пользователя из беседы
/setnick — поставить пользователю никнейм
/removenick — удалить никнейм пользователя
/nicklist — список ников
/mute — выдать мут
/unmute — размутить пользователя
        """,
        "senmoder": """
Команды старшего модератора:
/addmoder — выдать права модератора 
/removerole — забрать роль пользователя
/ban — заблокировать пользователя
/unban — разблокировать пользователя
        """,
        "admin": """
Команды администратора:
/addsenmoder — выдать права старшего модератора
/sban — заблокировать пользователя в сетке бесед
        """,
        "senadmin": """
Команды старшего администратора:
/addadmin — выдать права администратора пользователю
/gban — заблокировать пользователя во всех беседах
/gunban — разблокировать пользователя во всех беседах
        """,
        "depspec": """
Команды зам.спец администратора:
/addsenadmin — выдать права старшего админа
        """,
        "owner": """
Команды спец.администратора:
/addzsa — выдать права заместителя спец.администратора
/sync — синхронизировать беседу
        """
    }

    # Порядок ролей для накопления команд
    role_order = ["moder", "senmoder", "admin", "senadmin", "depspec", "owner"]

    if user_role in role_order:
        role_index = role_order.index(user_role)
        for i in range(role_index + 1):
            help_text += role_commands[role_order[i]]

    # Формируем клавиатуру с кнопкой "Альтернативные команды"
    main_keyboard = {
        "inline": True,
        "buttons": [
            [
                {
                    "action": {
                        "type": "text",
                        "label": "Альтернативные команды",
                        "payload": json.dumps({"command": "alt_commands"})
                    },
                    "color": "primary"
                }
            ]
        ]
    }

    # Отправляем сообщение с командами
    try:
        sent_message = await message.reply(help_text, keyboard=json.dumps(main_keyboard))
        help_cmid = sent_message.conversation_message_id  # Сохраняем ID сообщения
        logging.info(f"/help сообщение отправлено, conversation_message_id: {help_cmid}")
    except Exception as e:
        logging.error(f"Ошибка при отправке /help: {e}")
        await message.answer("Ошибка при отправке сообщения.")


@bot.on.message(payload={"command": "alt_commands"})
async def alt_commands_callback(message: Message):
    global help_cmid
    logging.info(f"Получена команда 'Альтернативные команды' от пользователя {message.from_id}")
    
    user_id = message.from_id
    chat_id = message.peer_id
    user_role = get_chat_user_role(chat_id, user_id)  # Функция получения роли из БД
    
    # Базовые команды для всех пользователей
    alt_text = """
Альтернативные команды

Команды пользователей:    
/info — инфо
/stats — стата, статистика
/getid — id, айди, ид
/bug — баг
    """

    # Команды для ролей
    role_commands = {
        "moder": """
Команды модератора:
/staff — стафф
/clear — чистка
/getnick — gnick
/kick — кик, исключить
/setnick — snick
/removenick — rnick, снятьник
/nicklist — ники, nlist
        """,
        "senmoder": """
Команды старшего модератора:
/addmoder — mod, moder, модер
/removerole — rrole, user
/ban — бан
/unban — разбан, removeban
        """,
        "admin": """
Команды администратора:
/addsenmoder — smod, senmoder, стмодер
/sban — null
        """,
        "senadmin": """
Команды старшего администратора:
/addadmin — админ
/gban — гбан
        """,
        "depspec": """
Команды зам.спец администратора:
/addsenadmin — sadmin
        """,
        "owner": """
Команды спец.администратора:
/addzsa — зса, depspec
/sync — синхрон
        """
    }

    # Определяем порядок ролей для накопления команд
    role_order = ["moder", "senmoder", "admin", "senadmin", "depspec", "owner"]

    if user_role in role_order:
        role_index = role_order.index(user_role)
        for i in range(role_index + 1):
            alt_text += role_commands[role_order[i]]

    # Удаление предыдущего сообщения с командами
    try:
        if help_cmid:
            await bot.api.messages.delete(
                cmids=[help_cmid],
                peer_id=chat_id,
                delete_for_all=True
            )
            logging.info(f"Удалено предыдущее /help сообщение, cmid: {help_cmid}")
            help_cmid = None
    except Exception as e:
        logging.error(f"Ошибка при удалении /help: {e}")

    # Удаление сообщения пользователя
    try:
        await bot.api.messages.delete(
            cmids=[message.conversation_message_id],
            peer_id=chat_id,
            delete_for_all=True
        )
        logging.info(f"Сообщение вызова alt_commands удалено, cmid: {message.conversation_message_id}")
    except Exception as e:
        logging.error(f"Ошибка при удалении вызова alt_commands: {e}")

    # Отправляем альтернативные команды
    try:
        sent_message = await message.answer(alt_text)
        logging.info(f"Альтернативные команды отправлены, cmid: {sent_message.conversation_message_id}")
    except Exception as e:
        logging.error(f"Ошибка при отправке альтернативных команд: {e}")

@bot.on.message(text="/info")
@bot.on.message(text="/инфо")
@bot.on.message(text="/информация")
@bot.on.message(text="/information")
@bot.on.message(text="/bot")
@bot.on.message(text="/бот")
@bot.on.message(text="!info")
@bot.on.message(text="!инфо")
@bot.on.message(text="!информация")
@bot.on.message(text="!information")
@bot.on.message(text="!bot")
@bot.on.message(text="!бот")
@bot.on.message(text="+info")
@bot.on.message(text="+инфо")
@bot.on.message(text="+информация")
@bot.on.message(text="+information")
@bot.on.message(text="+bot")
@bot.on.message(text="+бот")
async def info_command(message):
    await message.reply(
        """
Официальные ресурсы сервера SURGUT

Сообщество ВКонтакте — https://vk.com/surgut.blackrussia
Discord канал сервера —  https://discord.gg/U7jNHx67jm
Discord сервер проекта — https://discord.gg/blackrussia
Форумный раздел сервера — https://forum.blackrussia.online/forums/Сервер-№86-surgut.3781/
Главный администратор — https://vk.com/fedliza
Главный модератор — https://vk.com/n.ivanov.official
        """
    )

# ----- Пример дополнительных команд -----
@bot.on.message(text=[
    "/id <arg>", "/ид <arg>", "/айди <arg>", 
    "+id <arg>", "+ид <arg>", "+айди <arg>", 
    "!id <arg>", "!ид <arg>", "!айди <arg>"
])
async def id_handler(message: Message, arg: str):
    uid = await resolve_user_id(arg, bot)
    if not uid:
        await message.reply("Не удалось извлечь идентификатор пользователя из аргумента.")
        return
    await message.reply(f"Оригинальная ссылка на пользователя: https://vk.com/id{uid}")

@bot.on.message(text=[
    "/id", "/ид", "/айди", 
    "+id", "+ид", "+айди", 
    "!id", "!ид", "!айди"
])
async def id_reply_handler(message: Message):
    if message.reply_message:
        uid = message.reply_message.from_id
        await message.reply(f"Оригинальная ссылка на пользователя: https://vk.com/id{uid}")
    else:
        await message.reply("Вы не указали пользователя.")

@bot.on.message(text="/bug")
@bot.on.message(text="!bug")
@bot.on.message(text="+bug")
@bot.on.message(text="/баг")
@bot.on.message(text="!баг")
@bot.on.message(text="+баг")
async def ainfo_no_argument(message):
    await message.reply("Опишите проблему.")

@bot.on.message(text="/bug <text>")
@bot.on.message(text="!bug <text>")
@bot.on.message(text="+bug <text>")
@bot.on.message(text="/баг <text>")
@bot.on.message(text="!баг <text>")
@bot.on.message(text="+баг <text>")
async def bug_report_handler(message, text):
    if not text.strip():
        await message.reply("Укажите описание бага.")
        return

    sender_id = message.from_id
    sender_name = await get_user_name(sender_id)  # Получаем имя отправителя

    report_message = (f"🚨 Новый баг-репорт!\n"
                      f"👤 Отправитель: [https://vk.com/id{sender_id}|{sender_name}]\n"
                      f"💬 Сообщение: {text}")

    # Отправляем сообщение каждому админу
    for admin_id in ADMINS:
        try:
            await bot.api.messages.send(
                user_id=admin_id,
                random_id=0,
                message=report_message
            )
        except Exception as e:
            print(f"Ошибка при отправке админу {admin_id}: {e}")

    await message.reply("Ваш баг-репорт отправлен разработчику бота!")

@bot.on.message()
async def handle_all_messages(message: Message):
    chat_id = message.peer_id
    user_id = message.from_id
    db_name = get_db_name(chat_id)

    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT end_time FROM mutes WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()

    if result:
        end_time = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
        if datetime.now() < end_time:
            try:
                if message.conversation_message_id:  # Проверяем наличие cmid (для чатов)
                    await bot.api.messages.delete(
                        cmids=[message.conversation_message_id], 
                        peer_id=chat_id, 
                        delete_for_all=True
                    )
                elif message.message_id:  # Для личных сообщений
                    await bot.api.messages.delete(
                        message_ids=[message.message_id], 
                        delete_for_all=True
                    )
            except Exception as e:
                print(f"Ошибка при удалении сообщения: {e}")

    chat_id = message.peer_id
    members = await bot.api.messages.get_conversation_members(peer_id=chat_id)
    
    for member in members.items:
        # Проверяем, забанен ли участник
        ban_info = is_banned(chat_id, member.member_id)
        if ban_info:
            admin_id, ban_date = ban_info
            
            # Получаем имя администратора
            admin_name = await get_user_name(admin_id)
            
            # Формируем ссылку на профиль администратора
            admin_profile_link = f"[https://vk.com/id{admin_id}|{admin_name}]"
            
            # Получаем имя забаненного пользователя
            user_name = await get_user_name(member.member_id)
            
            try:
                # Исключаем пользователя из чата
                await bot.api.messages.remove_chat_user(chat_id=chat_id - 2000000000, member_id=member.member_id)
                
                # Отправляем сообщение о кике
                await bot.api.messages.send(
                    peer_id=chat_id,
                    message=(f"@id{member.member_id} ({user_name}) был исключен в связи с блокировкой.\n\n"
                             f"Выдал: {admin_profile_link}\nДата выдачи: {ban_date}"),
                    random_id=0
                )
            except Exception as e:
                print(f"Ошибка при кике {member.member_id}: {e}")

    # Отслеживание сообщений для регистрации пользователя
    """Обрабатывает все входящие сообщения."""
    if not message.text:
        return

    chat_id = message.peer_id
    user_id = message.from_id

    # Убедимся, что база данных для чата существует
    update_chat_db(chat_id)

    # Регистрируем или обновляем данные пользователя
    update_user_message_count(chat_id, user_id)



# ==============================
# Запуск бота
# ==============================
if __name__ == "__main__":
    # Инициализируем базу данных и необходимые столбцы
    initialize_columns()
    # Запускаем бота
    bot.run_forever()
