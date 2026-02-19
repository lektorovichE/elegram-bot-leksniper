import asyncio
import logging
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties
from openai import AsyncOpenAI

import config
import database

# --- ЛОГИРОВАНИЕ ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- СОСТОЯНИЯ FSM ---
class Order(StatesGroup):
    name = State()
    contact = State()
    ai_chat = State()
    wholesale = State()
    confirm = State() # Состояние для подтверждения заказа текстом

class AdminBroadcast(StatesGroup):
    message = State()

# --- ЗАГРУЗКА КАТАЛОГА ---
def load_catalog():
    """Безопасная загрузка каталога с обработкой ошибок"""
    try:
        with open("catalog.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Файл catalog.json не найден!")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга catalog.json: {e}")
        return {}

CATALOG = load_catalog()

# Создание словаря всех товаров для быстрого доступа
ALL_PRODUCTS = {}
catalog_for_ai = {}

if CATALOG:
    for cat_code, cat_data in CATALOG.items():
        catalog_for_ai[cat_data["name"]] = {}
        for subcat_code, subcat_data in cat_data["subcats"].items():
            for item in subcat_data["items"]:
                ALL_PRODUCTS[item["id"]] = {
                    **item, 
                    "cat_code": cat_code, 
                    "subcat_code": subcat_code
                }
            catalog_for_ai[cat_data["name"]][subcat_data["name"]] = [
                f"{item['name']} - {item['price']}" for item in subcat_data["items"]
            ]

# --- ИНИЦИАЛИЗАЦИЯ БОТА ---
bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Инициализация OpenAI клиента
try:
    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL)
except Exception as e:
    logger.error(f"Ошибка инициализации OpenAI: {e}")
    client = None

# --- КЛАВИАТУРЫ ---
def get_main_kb():
    """Главная клавиатура"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍 КАТАЛОГ")],
            [KeyboardButton(text="🤖 AI Ассистент")],
            [KeyboardButton(text="📦 Оптовый запрос / Гуманитарка")]
        ],
        resize_keyboard=True
    )

def get_cats_kb():
    """Клавиатура категорий"""
    if not CATALOG:
        return InlineKeyboardMarkup(inline_keyboard=[])
    
    buttons = [
        [InlineKeyboardButton(text=d["name"], callback_data=f"cat:{k}")] 
        for k, d in CATALOG.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_subcats_kb(cat_code):
    """Клавиатура подкатегорий"""
    if cat_code not in CATALOG:
        return InlineKeyboardMarkup(inline_keyboard=[])
    
    cat_data = CATALOG[cat_code]
    buttons = [
        [InlineKeyboardButton(text=d["name"], callback_data=f"sub:{cat_code}:{k}")] 
        for k, d in cat_data["subcats"].items()
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_items_kb(cat_code, subcat_code):
    """Клавиатура товаров"""
    if cat_code not in CATALOG or subcat_code not in CATALOG[cat_code]["subcats"]:
        return InlineKeyboardMarkup(inline_keyboard=[])
    
    subcat_data = CATALOG[cat_code]["subcats"][subcat_code]
    buttons = [
        [InlineKeyboardButton(
            text=f"{i['name']} | {i['price']}", 
            callback_data=f"prod:{i['id']}"
        )] 
        for i in subcat_data["items"]
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back:cat:{cat_code}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_prod_kb(pid):
    """Клавиатура товара"""
    if pid not in ALL_PRODUCTS:
        return InlineKeyboardMarkup(inline_keyboard=[])
    
    p = ALL_PRODUCTS[pid]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 КУПИТЬ", callback_data=f"buy:{pid}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back:sub:{p['cat_code']}:{p['subcat_code']}")]
    ])

def get_ai_exit_kb():
    """Клавиатура выхода из AI-чата"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Выйти из чата")]],
        resize_keyboard=True
    )

def get_admin_kb():
    """Клавиатура админ-панели"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="📩 Рассылка", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="📦 Список заказов", callback_data="admin:orders")],
        [InlineKeyboardButton(text="📋 Оптовые запросы", callback_data="admin:wholesale")]
    ])

# --- ОБРАБОТЧИКИ КОМАНД ---

@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    """Стартовое сообщение"""
    await state.clear()
    
    # Сохранение пользователя в БД
    await database.add_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name
    )
    
    welcome_text = (
        "<b>LEKSNIPER - Спецснаряжение</b>\n\n"
        "Приветствую! Я помогу выбрать лучшее снаряжение для боевых задач.\n\n"
        "Выберите раздел:"
    )
    
    await message.answer(welcome_text, reply_markup=get_main_kb())

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    """Админ-панель (только для админа)"""
    if message.from_user.id != config.ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    await message.answer(
        "🔐 <b>Админ-панель LEKSNIPER</b>\n\nВыберите действие:",
        reply_markup=get_admin_kb()
    )

# --- ОБРАБОТЧИКИ КНОПОК ГЛАВНОГО МЕНЮ ---

@dp.message(F.text == "🛍 КАТАЛОГ")
async def show_cats(message: types.Message, state: FSMContext):
    """Показ каталога категорий"""
    await state.clear()
    
    if not CATALOG:
        await message.answer("⚠️ Каталог временно недоступен. Попробуйте позже.")
        return
    
    await message.answer("Выберите категорию:", reply_markup=get_cats_kb())

@dp.message(F.text == "🤖 AI Ассистент")
async def ai_start(message: types.Message, state: FSMContext):
    """Запуск AI-ассистента"""
    if not client:
        await message.answer("⚠️ AI-ассистент временно недоступен.")
        return
    
    await state.set_state(Order.ai_chat)
    await message.answer(
        "🤖 <b>AI Ассистент LEKSNIPER активирован!</b>\n\n"
        "Я помогу вам выбрать снаряжение и объясню, почему наше качество превосходит китайские аналоги.\n\n"
        "Задавайте любые вопросы!",
        reply_markup=get_ai_exit_kb()
    )

@dp.message(F.text == "📦 Оптовый запрос / Гуманитарка")
async def wholesale_start(message: types.Message, state: FSMContext):
    """Оптовый запрос"""
    await state.set_state(Order.wholesale)
    await message.answer(
        "📦 <b>Оптовые закупки и Гуманитарная помощь</b>\n\n"
        "Для оптовых заказчиков и гуманитарных миссий у нас особые условия.\n\n"
        "<b>Пришлите список нужных товаров и цены, которые вам предложили другие — "
        "мы сделаем предложение выгоднее!</b>",
        reply_markup=get_ai_exit_kb()
    )

@dp.message(F.text == "❌ Выйти из чата")
async def ai_exit(message: types.Message, state: FSMContext):
    """Выход из AI-чата / оптового режима"""
    await state.clear()
    await message.answer("Возвращаюсь в главное меню.", reply_markup=get_main_kb())

# --- ОБРАБОТЧИКИ AI-ЧАТА ---

@dp.message(Order.ai_chat)
async def ai_handler(message: types.Message, state: FSMContext):
    """Обработка сообщений в AI-чате"""
    if not message.text:
        return
    
    await bot.send_chat_action(message.chat.id, "typing")
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": config.SYSTEM_PROMPT + f"\n\nКАТАЛОГ ТОВАРОВ:\n{json.dumps(catalog_for_ai, ensure_ascii=False)}"
                },
                {"role": "user", "content": message.text}
            ]
        )
        
        ai_text = response.choices[0].message.content
        
        # --- ЕДИНАЯ ЛОГИКА ПЕРЕХВАТА ЗАКАЗА ---
        low_ai_text = ai_text.lower()
        
        # Ищем товар в ответе AI
        found_pid = None
        for pid, p_data in ALL_PRODUCTS.items():
            if p_data['name'].lower() in low_ai_text:
                found_pid = pid
                break
        
        # Если AI упомянул товар и слова про оформление/заказ
        if found_pid and any(word in low_ai_text for word in ["оформить", "заказ", "купить", "оформляем"]):
            await state.update_data(pid=found_pid)
            
            # Если AI уже "приступает" или "оформляет", сразу идем на ФИО
            if any(word in low_ai_text for word in ["приступаю", "оформляем", "информация", "данные"]):
                await message.answer(ai_text)
                await message.answer(
                    f"Начинаем оформление <b>{ALL_PRODUCTS[found_pid]['name']}</b>.\n\n"
                    "Пожалуйста, введите ваше <b>ФИО</b>:",
                    reply_markup=types.ReplyKeyboardRemove()
                )
                await state.set_state(Order.name)
                return
            else:
                # В остальных случаях ждем подтверждения "да"
                await state.set_state(Order.confirm)
                await message.answer(ai_text)
                return
        
        await message.answer(ai_text)
        
    except Exception as e:
        logger.error(f"Ошибка AI API: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при обращении к AI-ассистенту. "
            "Попробуйте позже или свяжитесь с поддержкой."
        )

# --- ОБРАБОТЧИКИ ОПТОВОГО РЕЖИМА ---

# --- ХЕНДЛЕР ПОДТВЕРЖДЕНИЯ ЗАКАЗА ---
@dp.message(Order.confirm)
async def confirm_handler(message: types.Message, state: FSMContext):
    """Обработка подтверждения заказа (да/нет)"""
    if not message.text:
        return
        
    text = message.text.lower().strip()
    # Расширенный список слов-подтверждений
    confirm_words = ["да", "согласен", "оформляй", "беру", "ок", "хорошо", "давай", "хочу", "подтверждаю", "какая", "что нужно"]
    
    data = await state.get_data()
    pid = data.get("pid")
    product_name = ALL_PRODUCTS[pid]['name'] if pid in ALL_PRODUCTS else "товар"

    if any(word in text for word in confirm_words):
        if pid and pid in ALL_PRODUCTS:
            await message.answer(
                f"Для оформления заказа на <b>{product_name}</b> мне понадобятся ваши данные.\n\n"
                "Пожалуйста, введите ваше <b>ФИО</b>:",
                reply_markup=types.ReplyKeyboardRemove()
            )
            await state.set_state(Order.name)
        else:
            await message.answer("⚠️ Товар не выбран. Пожалуйста, напишите название товара еще раз.", reply_markup=get_ai_exit_kb())
            await state.set_state(Order.ai_chat)
    elif any(word in text for word in ["нет", "отмена", "не надо", "стоп"]):
        await message.answer("Понял, отменяем оформление. Возвращаюсь в режим консультации.", reply_markup=get_ai_exit_kb())
        await state.set_state(Order.ai_chat)
    else:
        # ЛИПКАЯ ЛОГИКА: Если мы в режиме подтверждения, не пускаем в AI, пока не ответит по делу
        await message.answer(
            f"Мы сейчас оформляем заказ на <b>{product_name}</b>.\n\n"
            "Вы согласны продолжить? Напишите 'Да' или 'Нет'.",
            reply_markup=get_ai_exit_kb()
        )

@dp.message(Order.wholesale)
async def wholesale_handler(message: types.Message, state: FSMContext):
    """Обработка оптового запроса"""
    if not message.text:
        return
    
    try:
        # Сохранение запроса в БД
        await database.add_wholesale_request(
            user_id=message.from_user.id,
            username=message.from_user.username or "без username",
            request_text=message.text
        )
        
        # Уведомление админу
        admin_msg = (
            f"🚨 <b>НОВЫЙ ОПТОВЫЙ ЗАПРОС!</b>\n\n"
            f"От: @{message.from_user.username or 'без username'}\n"
            f"ID: <code>{message.from_user.id}</code>\n\n"
            f"<b>Текст запроса:</b>\n{message.text}"
        )
        await bot.send_message(config.ADMIN_ID, admin_msg)
        
        # Подтверждение клиенту
        await message.answer(
            "✅ <b>Ваш запрос принят!</b>\n\n"
            "Мы изучим ваш список и свяжемся с вами в ближайшее время, "
            "чтобы предложить лучшие условия.",
            reply_markup=get_main_kb()
        )
        
    except Exception as e:
        logger.error(f"Ошибка обработки оптового запроса: {e}")
        await message.answer(
            "⚠️ Произошла ошибка. Попробуйте позже или свяжитесь напрямую с поддержкой."
        )
    
    await state.clear()

# --- ОФОРМЛЕНИЕ ЗАКАЗА (FSM) ---

@dp.message(Order.name)
async def process_name(message: types.Message, state: FSMContext):
    """Получение имени клиента"""
    await state.update_data(name=message.text)
    await message.answer("Введите ваш номер телефона или ник в Telegram для связи:")
    await state.set_state(Order.contact)

@dp.message(Order.contact)
async def process_contact(message: types.Message, state: FSMContext):
    """Получение контакта и завершение заказа"""
    data = await state.get_data()
    pid = data.get('pid')
    
    if not pid or pid not in ALL_PRODUCTS:
        await message.answer("⚠️ Ошибка: товар не найден.", reply_markup=get_main_kb())
        await state.clear()
        return
    
    p = ALL_PRODUCTS[pid]
    customer_name = data['name']
    contact = message.text
    
    try:
        # Сохранение заказа в БД
        await database.add_order(
            user_id=message.from_user.id,
            user_name=message.from_user.username or "без username",
            customer_name=customer_name,
            contact=contact,
            item_id=pid,
            item_name=p['name'],
            item_price=p['price']
        )
        
        # Уведомление админу
        admin_msg = (
            f"💰 <b>НОВЫЙ ЗАКАЗ!</b>\n\n"
            f"<b>Товар:</b> {p['name']} (ID: {pid})\n"
            f"<b>Цена:</b> {p['price']}\n\n"
            f"<b>Клиент:</b>\n"
            f"ФИО: {customer_name}\n"
            f"Связь: {contact}\n"
            f"Username: @{message.from_user.username or 'нет'}\n"
            f"User ID: <code>{message.from_user.id}</code>"
        )
        await bot.send_message(config.ADMIN_ID, admin_msg)
        
        # Подтверждение клиенту
        await message.answer(
            "✅ <b>Спасибо! Ваш заказ принят.</b>\n\n"
            "Менеджер свяжется с вами в ближайшее время для уточнения деталей доставки.",
            reply_markup=get_main_kb()
        )
        
    except Exception as e:
        logger.error(f"Ошибка оформления заказа: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при оформлении заказа. "
            "Попробуйте позже или свяжитесь с поддержкой.",
            reply_markup=get_main_kb()
        )
    
    await state.clear()

# --- ОБРАБОТЧИКИ CALLBACK (НАВИГАЦИЯ ПО КАТАЛОГУ) ---

@dp.callback_query(F.data.startswith("cat:"))
async def show_subcats(callback: types.CallbackQuery):
    """Показ подкатегорий"""
    cat_code = callback.data.split(":")[1]
    
    if cat_code not in CATALOG:
        await callback.answer("❌ Категория не найдена")
        return
    
    try:
        await callback.message.edit_text(
            f"<b>{CATALOG[cat_code]['name']}</b>\n\nВыберите подкатегорию:",
            reply_markup=get_subcats_kb(cat_code)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка показа подкатегорий: {e}")
        await callback.answer("⚠️ Ошибка отображения")

@dp.callback_query(F.data.startswith("sub:"))
async def show_items(callback: types.CallbackQuery):
    """Показ товаров подкатегории"""
    _, cat_code, subcat_code = callback.data.split(":")
    
    if cat_code not in CATALOG or subcat_code not in CATALOG[cat_code]["subcats"]:
        await callback.answer("❌ Подкатегория не найдена")
        return
    
    try:
        subcat_name = CATALOG[cat_code]["subcats"][subcat_code]["name"]
        await callback.message.edit_text(
            f"<b>{subcat_name}</b>\n\nВыберите товар:",
            reply_markup=get_items_kb(cat_code, subcat_code)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка показа товаров: {e}")
        await callback.answer("⚠️ Ошибка отображения")

@dp.callback_query(F.data.startswith("prod:"))
async def show_prod(callback: types.CallbackQuery):
    """Показ карточки товара"""
    pid = callback.data.split(":")[1]
    
    if pid not in ALL_PRODUCTS:
        await callback.answer("❌ Товар не найден")
        return
    
    try:
        p = ALL_PRODUCTS[pid]
        text = f"<b>{p['name']}</b>\n\n{p['desc']}\n\n💰 Цена: <b>{p['price']}</b>"
        
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=p['photo'],
            caption=text,
            reply_markup=get_prod_kb(pid)
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка показа товара: {e}")
        await callback.answer("⚠️ Ошибка загрузки фото")

@dp.callback_query(F.data.startswith("buy:"))
async def buy_item(callback: types.CallbackQuery, state: FSMContext):
    """Начало оформления заказа"""
    pid = callback.data.split(":")[1]
    
    if pid not in ALL_PRODUCTS:
        await callback.answer("❌ Товар не найден")
        return
    
    await state.update_data(pid=pid)
    await callback.message.answer(
        f"Оформляем заказ на <b>{ALL_PRODUCTS[pid]['name']}</b>.\n\n"
        "Введите ваше ФИО:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(Order.name)
    await callback.answer()

# --- НАВИГАЦИЯ "НАЗАД" ---

@dp.callback_query(F.data == "back:main")
async def back_main(callback: types.CallbackQuery):
    """Возврат к главным категориям"""
    try:
        await callback.message.edit_text(
            "Выберите категорию:",
            reply_markup=get_cats_kb()
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка навигации назад: {e}")

@dp.callback_query(F.data.startswith("back:cat:"))
async def back_cat(callback: types.CallbackQuery):
    """Возврат к подкатегориям"""
    cat_code = callback.data.split(":")[2]
    
    if cat_code not in CATALOG:
        await callback.answer("❌ Категория не найдена")
        return
    
    try:
        await callback.message.edit_text(
            f"<b>{CATALOG[cat_code]['name']}</b>\n\nВыберите подкатегорию:",
            reply_markup=get_subcats_kb(cat_code)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка навигации назад: {e}")

@dp.callback_query(F.data.startswith("back:sub:"))
async def back_sub(callback: types.CallbackQuery):
    """Возврат к списку товаров"""
    _, _, cat_code, subcat_code = callback.data.split(":")
    
    if cat_code not in CATALOG or subcat_code not in CATALOG[cat_code]["subcats"]:
        await callback.answer("❌ Подкатегория не найдена")
        return
    
    try:
        subcat_name = CATALOG[cat_code]["subcats"][subcat_code]["name"]
        await callback.message.delete()
        await callback.message.answer(
            f"<b>{subcat_name}</b>\n\nВыберите товар:",
            reply_markup=get_items_kb(cat_code, subcat_code)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка навигации назад: {e}")

# --- АДМИН-ПАНЕЛЬ ---

@dp.callback_query(F.data == "admin:stats")
async def admin_stats(callback: types.CallbackQuery):
    """Статистика бота"""
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("❌ Нет доступа")
        return
    
    try:
        users_count = await database.get_users_count()
        orders_count = await database.get_orders_count()
        
        stats_text = (
            "📊 <b>Статистика LEKSNIPER Bot</b>\n\n"
            f"👥 Всего пользователей: <b>{users_count}</b>\n"
            f"📦 Всего заказов: <b>{orders_count}</b>"
        )
        
        await callback.message.edit_text(stats_text, reply_markup=get_admin_kb())
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        await callback.answer("⚠️ Ошибка загрузки статистики")

@dp.callback_query(F.data == "admin:orders")
async def admin_orders(callback: types.CallbackQuery):
    """Список заказов"""
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("❌ Нет доступа")
        return
    
    try:
        orders = await database.get_all_orders(limit=10)
        
        if not orders:
            text = "📦 Заказов пока нет."
        else:
            text = "📦 <b>Последние 10 заказов:</b>\n\n"
            for order in orders:
                order_id, user_name, customer_name, contact, item_name, price, status, created = order
                text += (
                    f"<b>#{order_id}</b> | {item_name}\n"
                    f"👤 {customer_name} (@{user_name})\n"
                    f"📞 {contact} | 💰 {price}\n"
                    f"📅 {created[:16]}\n\n"
                )
        
        await callback.message.edit_text(text, reply_markup=get_admin_kb())
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка получения заказов: {e}")
        await callback.answer("⚠️ Ошибка загрузки заказов")

@dp.callback_query(F.data == "admin:wholesale")
async def admin_wholesale(callback: types.CallbackQuery):
    """Оптовые запросы"""
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("❌ Нет доступа")
        return
    
    try:
        requests = await database.get_wholesale_requests(limit=5)
        
        if not requests:
            text = "📋 Оптовых запросов пока нет."
        else:
            text = "📋 <b>Последние 5 оптовых запросов:</b>\n\n"
            for req in requests:
                req_id, username, req_text, created = req
                text += (
                    f"<b>#{req_id}</b> | @{username}\n"
                    f"{req_text[:100]}...\n"
                    f"📅 {created[:16]}\n\n"
                )
        
        await callback.message.edit_text(text, reply_markup=get_admin_kb())
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка получения оптовых запросов: {e}")
        await callback.answer("⚠️ Ошибка загрузки")

@dp.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало рассылки"""
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("❌ Нет доступа")
        return
    
    await callback.message.edit_text("📩 <b>Рассылка</b>\n\nВведите текст сообщения для рассылки:")
    await state.set_state(AdminBroadcast.message)
    await callback.answer()

@dp.message(AdminBroadcast.message)
async def admin_broadcast_send(message: types.Message, state: FSMContext):
    """Отправка рассылки"""
    if message.from_user.id != config.ADMIN_ID:
        await state.clear()
        return
    
    broadcast_text = message.text
    
    try:
        users = await database.get_all_users()
        
        if not users:
            await message.answer("❌ Нет пользователей для рассылки.")
            await state.clear()
            return
        
        success = 0
        failed = 0
        
        await message.answer(f"📤 Начинаю рассылку для {len(users)} пользователей...")
        
        for user_id, username, first_name in users:
            try:
                await bot.send_message(chat_id=user_id, text=broadcast_text)
                success += 1
                await asyncio.sleep(0.05)  # Защита от флуда
            except Exception as e:
                logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
                failed += 1
        
        result_text = (
            f"✅ <b>Рассылка завершена!</b>\n\n"
            f"📨 Успешно: {success}\n"
            f"❌ Ошибок: {failed}"
        )
        
        await message.answer(result_text)
        
    except Exception as e:
        logger.error(f"Ошибка рассылки: {e}")
        await message.answer("⚠️ Произошла ошибка при рассылке.")
    
    await state.clear()

# --- ЗАПУСК БОТА ---

async def main():
    """Основная функция запуска"""
    try:
        # Инициализация базы данных
        await database.init_db()
        logger.info("База данных инициализирована")
        
        # Запуск бота
        logger.info("Бот запущен!")
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())