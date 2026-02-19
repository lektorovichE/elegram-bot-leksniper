import aiosqlite
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = "bot_database.db"

async def init_db():
    """Инициализация базы данных с расширенными таблицами"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Таблица пользователей для рассылок
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Расширенная таблица заказов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    user_name TEXT,
                    customer_name TEXT,
                    contact TEXT,
                    item_id TEXT,
                    item_name TEXT,
                    item_price TEXT,
                    status TEXT DEFAULT 'new',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица оптовых запросов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS wholesale_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT,
                    request_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.commit()
            logger.info("База данных успешно инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")
        raise

async def add_user(user_id, username=None, first_name=None, last_name=None):
    """Добавление или обновление пользователя"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, last_activity)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    last_activity = excluded.last_activity
            """, (user_id, username, first_name, last_name, datetime.now()))
            await db.commit()
            logger.info(f"Пользователь {user_id} добавлен/обновлен")
    except Exception as e:
        logger.error(f"Ошибка добавления пользователя {user_id}: {e}")

async def add_order(user_id, user_name, customer_name, contact, item_id, item_name, item_price):
    """Добавление заказа с полной информацией"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO orders (user_id, user_name, customer_name, contact, item_id, item_name, item_price)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, user_name, customer_name, contact, item_id, item_name, item_price))
            await db.commit()
            logger.info(f"Заказ от {user_id} ({customer_name}) на {item_name} создан")
    except Exception as e:
        logger.error(f"Ошибка создания заказа: {e}")

async def add_wholesale_request(user_id, username, request_text):
    """Добавление оптового запроса"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO wholesale_requests (user_id, username, request_text)
                VALUES (?, ?, ?)
            """, (user_id, username, request_text))
            await db.commit()
            logger.info(f"Оптовый запрос от {user_id} сохранен")
    except Exception as e:
        logger.error(f"Ошибка сохранения оптового запроса: {e}")

async def get_all_users():
    """Получение всех пользователей для рассылки"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT user_id, username, first_name FROM users") as cursor:
                users = await cursor.fetchall()
                logger.info(f"Получено {len(users)} пользователей")
                return users
    except Exception as e:
        logger.error(f"Ошибка получения пользователей: {e}")
        return []

async def get_users_count():
    """Получение количества пользователей"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                result = await cursor.fetchone()
                return result[0] if result else 0
    except Exception as e:
        logger.error(f"Ошибка подсчета пользователей: {e}")
        return 0

async def get_orders_count():
    """Получение количества заказов"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM orders") as cursor:
                result = await cursor.fetchone()
                return result[0] if result else 0
    except Exception as e:
        logger.error(f"Ошибка подсчета заказов: {e}")
        return 0

async def get_all_orders(limit=20):
    """Получение последних заказов"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("""
                SELECT id, user_name, customer_name, contact, item_name, item_price, status, created_at
                FROM orders
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)) as cursor:
                orders = await cursor.fetchall()
                logger.info(f"Получено {len(orders)} заказов")
                return orders
    except Exception as e:
        logger.error(f"Ошибка получения заказов: {e}")
        return []

async def get_wholesale_requests(limit=10):
    """Получение оптовых запросов"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("""
                SELECT id, username, request_text, created_at
                FROM wholesale_requests
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)) as cursor:
                requests = await cursor.fetchall()
                return requests
    except Exception as e:
        logger.error(f"Ошибка получения оптовых запросов: {e}")
        return []