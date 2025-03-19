import os
import sqlite3
from datetime import datetime
from vkbottle.bot import Bot, Message
from vkbottle import API

TOKEN = "vk1.a.5bWRa7wwHUl-VkHE7sbxa9huYX1cHxZLFeNOa7H7xeNW-GK5ZGngviGtjF4D2eFkeWtIqdJI00TXK-NU4SpznSRMck0pekmPd0JTvAFMGUDu0_q93XeonG0MSAXkV931iPFTr0F7Ilzka4PW9ArlYAQgH14XznPIeC3LvzjDj3JMhhD_ZOstbBtJRrdUkTvwtxWc7pNJ8uigTj4_Q-hQjA"
bot = Bot(token=TOKEN)
api = API(TOKEN)

# Функция для получения пути к БД беседы
def get_db_name(chat_id: int) -> str:
    os.makedirs("chats", exist_ok=True)
    return os.path.join("chats", f"chat_{chat_id}.db")

def create_chat_db(chat_id: int):
    """
    Создаёт базу данных для чата с таблицей users и таблицей banned_users.
    
    Таблица users:
      - id (INTEGER PRIMARY KEY)
      - role (TEXT, по умолчанию 'user')
      - count_messages (INTEGER, по умолчанию 0)
      - last_messages (TEXT)
      - ban (INTEGER, по умолчанию 0)
      - warn (INTEGER, по умолчанию 0)
      - mute (INTEGER, по умолчанию 0)
    
    Таблица banned_users:
      - user_id (INTEGER PRIMARY KEY) – ID заблокированного пользователя
      - admin_id (INTEGER) – ID пользователя, выдавшего бан
      - reason (TEXT) – причина блокировки
      - ban_date (TEXT) – дата и время блокировки
    """
    db_name = get_db_name(chat_id)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    # Создаем таблицу users, если её нет
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
    
    # Создаем таблицу banned_users, если её нет
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            admin_id INTEGER,
            reason TEXT,
            ban_date TEXT
        )
    """)
    
    conn.commit()
    conn.close()

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


async def extract_user_id_from_reply(message: Message):
    if message.reply_message:
        return message.reply_message.from_id
    return None

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

@bot.on.message(text="/ban <target> <reason>")
async def ban_user_with_target(message: Message, target: str, reason: str):
    await process_ban(message, target, reason)

@bot.on.message(text="/ban <reason>")
async def ban_user_with_reply(message: Message, reason: str):
    if not message.reply_message:
        await message.reply("⚠ Укажите пользователя (упоминание, ссылка или ответ на сообщение).")
        return
    target_id = message.reply_message.from_id
    await process_ban(message, target_id, reason)

async def process_ban(message: Message, target: str | int, reason: str):
    chat_id = message.peer_id
    admin_id = message.from_id

    if isinstance(target, str):
        target_id = await extract_user_id_from_target(target)
    else:
        target_id = target

    if not target_id:
        await message.reply("⚠ Не удалось определить пользователя.")
        return

    if is_banned(chat_id, target_id):
        await message.reply("🚫 Этот пользователь уже в бане.")
        return

    add_banned_user(chat_id, target_id, admin_id, reason)

    try:
        await bot.api.messages.remove_chat_user(chat_id=chat_id - 2000000000, member_id=target_id)
        await message.reply(f"✅ Пользователь [id{target_id}|{await get_user_name(target_id)}] забанен.\n📌 Причина: {reason}")
    except Exception as e:
        await message.reply(f"⚠ Ошибка при кике: {e}")



@bot.on.message(text="/unban <target>")
async def unban_user_with_target(message: Message, target: str):
    await process_unban(message, target)

@bot.on.message(text="/unban")
async def unban_user_with_reply(message: Message):
    if not message.reply_message:
        await message.reply("⚠ Укажите пользователя (упоминание, ссылка или ответ на сообщение).")
        return
    target_id = message.reply_message.from_id
    await process_unban(message, target_id)

async def process_unban(message: Message, target: str | int):
    chat_id = message.peer_id

    if isinstance(target, str):
        target_id = await extract_user_id_from_target(target)
    else:
        target_id = target

    if not target_id:
        await message.reply("⚠ Не удалось определить пользователя.")
        return

    if not is_banned(chat_id, target_id):
        await message.reply("🚫 Этот пользователь не забанен.")
        return

    remove_banned_user(chat_id, target_id)
    await message.reply(f"✅ Пользователь [id{target_id}|{await get_user_name(target_id)}] разбанен.")



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
async def gsync(message: Message):
    chat_id = message.peer_id  # для беседы (peer_id >= 2000000000)
    create_chat_db(chat_id)  # Создаем базу данных для беседы

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

        await message.reply(f"✅ База данных для беседы {chat_id} создана и синхронизация прошла успешно!")

    except Exception as e:
        await message.reply(f"Ошибка при синхронизации: {e}")

@bot.on.message(text="/gban <target> <reason>")
async def global_ban(message: Message, target: str, reason: str):
    admin_id = message.from_id
    admin_name = await get_user_name(admin_id)
    
    # Пробуем сначала получить ID из упоминания/ссылки
    target_id = await extract_user_id_from_target(message, target)
    
    if not target_id:
        await message.reply("⚠ Не удалось определить пользователя.")
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
    
    await message.reply(f"✅ Пользователь [id{target_id}|{await get_user_name(target_id)}] был заблокирован и исключен из всех бесед.")


@bot.on.message(text="/gban <reason>")
async def global_ban_by_reply(message: Message, reason: str):
    admin_id = message.from_id
    admin_name = await get_user_name(admin_id)
    
    # Извлекаем ID из ответа на сообщение
    target_id = await extract_user_id_from_reply(message)
    
    if not target_id:
        await message.reply("⚠ Не удалось определить пользователя.")
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
    
    await message.reply(f"✅ Пользователь [id{target_id}|{await get_user_name(target_id)}] был заблокирован и исключен из всех бесед.")


@bot.on.message(text="/gunban <target>")
async def global_unban_with_target(message: Message, target: str):
    await process_global_unban(message, target)

@bot.on.message(text="/gunban")
async def global_unban_with_reply(message: Message):
    if not message.reply_message:
        await message.reply("⚠ Укажите пользователя (упоминание, ссылка или ответ на сообщение).")
        return
    target_id = message.reply_message.from_id
    await process_global_unban(message, target_id)

async def process_global_unban(message: Message, target: str | int):
    admin_id = message.from_id

    if isinstance(target, str):
        target_id = await extract_user_id_from_target(target)
    else:
        target_id = target

    if not target_id:
        await message.reply("⚠ Не удалось определить пользователя.")
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

    await message.reply(f"✅ Пользователь [id{target_id}|{await get_user_name(target_id)}] разбанен во всех беседах.")




# Функция для автоматического кика забаненных пользователей с использованием get_user_name
# Функция для автоматического кика забаненных пользователей с использованием get_user_name
@bot.on.chat_message()
async def auto_kick_banned_users(message: Message):
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




bot.run_forever()
