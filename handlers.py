import io
import logging
from aiogram import Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from yandex_service import YandexService
from state_manager import state_manager

ai_service = YandexService()
logger = logging.getLogger(__name__)

# --- СЛОВАРЬ КАТЕГОРИЙ (Для отображения) ---
CATEGORY_MAP = {
    "breakfast": "🍳 Завтраки",
    "soup": "🍲 Супы",
    "main": "🍝 Вторые блюда",
    "salad": "🥗 Салаты",
    "snack": "🥪 Закуски",
    "dessert": "🍰 Десерты",
    "drink": "🥤 Напитки",
}

# --- КЛАВИАТУРЫ ---

def get_style_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Классический / Домашний", callback_data="style_ordinary")],
        [InlineKeyboardButton(text="🌶 Экзотический / Необычный", callback_data="style_exotic")]
    ])

def get_categories_keyboard(categories: list):
    builder = []
    row = []
    for cat_key in categories:
        text = CATEGORY_MAP.get(cat_key, cat_key.capitalize())
        row.append(InlineKeyboardButton(text=text, callback_data=f"cat_{cat_key}"))
        if len(row) == 2: # По 2 кнопки в ряд
            builder.append(row)
            row = []
    if row: builder.append(row)
    
    # Кнопка сброса
    builder.append([InlineKeyboardButton(text="🗑 Сброс (Начать заново)", callback_data="restart")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_dishes_keyboard(dishes_list: list):
    builder = []
    for i, dish in enumerate(dishes_list):
        btn_text = f"{dish['name'][:40]}" # Чистый текст, без эмодзи (или можно буллит)
        builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"dish_{i}")])
    
    # Кнопка НАЗАД К КАТЕГОРИЯМ
    builder.append([InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_recipe_back_keyboard():
    # ТОЛЬКО КНОПКА ВОЗВРАТА
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Вернуться к категориям", callback_data="back_to_categories")]
    ])

def get_hide_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 Скрыть", callback_data="delete_msg")]])

# --- ХЭНДЛЕРЫ ---

async def cmd_start(message: Message):
    state_manager.clear_session(message.from_user.id)
    text = (
        "👋 Здравствуйте.\n\n"
        "🎤 <b>Отправьте</b> голосовое или текстовое сообщение с перечнем продуктов, и я подскажу, что из них можно приготовить.\n"
        '📝 Или напишите <b>"Дай рецепт [блюдо]"</b>.'
    )
    await message.answer(text, parse_mode="HTML")

async def cmd_author(message: Message):
    await message.answer("👨‍💻 Автор бота: @inikonoff")

# --- Прямой запрос (без категорий) ---
async def handle_direct_recipe(message: Message):
    user_id = message.from_user.id
    dish_name = message.text[10:].strip() 
    if len(dish_name) < 3:
        await message.answer("Напишите название блюда.", parse_mode="HTML")
        return

    wait = await message.answer(f"⚡️ Ищу: <b>{dish_name}</b>...", parse_mode="HTML")
    try:
        recipe = await ai_service.generate_freestyle_recipe(dish_name)
        await wait.delete()
        # Для прямых запросов "Назад" не актуален, оставляем "Скрыть"
        await message.answer(recipe, reply_markup=get_hide_keyboard(), parse_mode="HTML")
        state_manager.set_state(user_id, "recipe_sent")
    except Exception:
        await wait.delete()
        await message.answer("Ошибка генерации.")

async def handle_delete_msg(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

async def handle_voice(message: Message):
    user_id = message.from_user.id
    processing_msg = await message.answer("🎧 Слушаю...")
    try:
        voice_file = io.BytesIO()
        await message.bot.download(message.voice, destination=voice_file)
        text = await ai_service.speech_to_text(voice_file.getvalue())
        await processing_msg.delete()
        if not text:
            await message.answer("😕 Тишина.")
            return
        try: await message.delete()
        except: pass
        await process_products_input(message, user_id, text)
    except Exception:
        await processing_msg.delete()

async def handle_text(message: Message):
    await process_products_input(message, message.from_user.id, message.text)

# --- ГЛАВНАЯ ЛОГИКА ---
async def process_products_input(message: Message, user_id: int, text: str):
    # Пасхалка
    if text.lower().strip(" .!") in ["спасибо", "спс", "благодарю"]:
        if state_manager.get_state(user_id) == "recipe_sent":
            await message.answer("На здоровье! 👨‍🍳")
            state_manager.clear_state(user_id)
            return

    if state_manager.get_state(user_id) == "recipe_sent":
        state_manager.clear_state(user_id)

    products_in_memory = state_manager.get_products(user_id)
    
    # 1. Если продуктов еще нет -> Сохраняем и спрашиваем стиль (старт сессии)
    if not products_in_memory:
        is_valid = await ai_service.validate_ingredients(text)
        if not is_valid:
            await message.answer(f"🤨 <b>\"{text}\"</b> — не похоже на продукты.", parse_mode="HTML")
            return
        state_manager.set_products(user_id, text)
        state_manager.add_message(user_id, "user", text)
        # Сразу предлагаем стиль, а анализ категорий будет после стиля
        await message.answer(f"✅ Продукты приняты.\nКакой стиль готовки?", reply_markup=get_style_keyboard(), parse_mode="HTML")
        return

    # 2. Если продукты уже есть -> Определяем намерение (добавка или бред)
    last_bot_msg = state_manager.get_last_bot_message(user_id) or ""
    intent_data = await ai_service.determine_intent(text, last_bot_msg)
    
    if intent_data.get("intent") == "add_products" or True: # Упрощаем: почти любой текст считаем добавкой
        # Добавляем продукты и перезапускаем анализ категорий
        state_manager.append_products(user_id, text)
        await message.answer(f"➕ Добавил: <b>{text}</b>.", parse_mode="HTML")
        
        # Запускаем флоу категорий заново (как будто стиль уже выбран "обычный")
        all_products = state_manager.get_products(user_id)
        await start_category_flow(message, user_id, all_products, "с учетом новых продуктов")

# --- ЛОГИКА КАТЕГОРИЙ И БЛЮД ---

async def start_category_flow(message: Message, user_id: int, products: str, style: str):
    wait = await message.answer("👨‍🍳 Анализирую продукты...")
    
    # 1. Получаем категории
    categories = await ai_service.analyze_categories(products)
    
    await wait.delete()
    
    if not categories:
        await message.answer("Из этого сложно что-то приготовить. Добавьте еще продуктов.")
        return

    # Сохраняем категории
    state_manager.set_categories(user_id, categories)

    # 2. Если категория всего одна (например, только 'main') -> Сразу генерируем блюда
    if len(categories) == 1:
        await show_dishes_for_category(message, user_id, products, categories[0], style)
    else:
        # 3. Показываем меню выбора категорий
        await message.answer("📂 <b>Что будем готовить?</b>", reply_markup=get_categories_keyboard(categories), parse_mode="HTML")

async def show_dishes_for_category(message: Message, user_id: int, products: str, category: str, style: str):
    cat_name = CATEGORY_MAP.get(category, "Блюда")
    wait = await message.answer(f"🍳 Придумываю {cat_name}...")
    
    dishes_list = await ai_service.generate_dishes_list(products, category, style)
    
    if not dishes_list:
        await wait.delete()
        await message.answer("Не удалось придумать рецепты. Попробуйте другую категорию.")
        return

    state_manager.set_generated_dishes(user_id, dishes_list)
    
    response_text = f"🍽 <b>Меню: {cat_name}</b>\n\n"
    for dish in dishes_list:
        response_text += f"🔸 <b>{dish['name']}</b>\n<i>{dish['desc']}</i>\n\n"
    
    state_manager.add_message(user_id, "bot", response_text)
    
    await wait.delete()
    await message.answer(response_text, reply_markup=get_dishes_keyboard(dishes_list), parse_mode="HTML")


# --- CALLBACKS ---

async def handle_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    data = callback.data
    
    if data == "restart":
        state_manager.clear_session(user_id)
        await callback.message.answer("🗑 Жду продукты.")
        await callback.answer()
        return

    # ВЫБОР СТИЛЯ -> ЗАПУСК КАТЕГОРИЙ
    if data.startswith("style_"):
        style = "домашний" if "ordinary" in data else "экзотический"
        products = state_manager.get_products(user_id)
        if not products:
            await callback.message.answer("Список пуст. /start")
            return
        
        await callback.message.delete()
        await start_category_flow(callback.message, user_id, products, style)
        await callback.answer()
        return

    # ВЫБОР КАТЕГОРИИ
    if data.startswith("cat_"):
        category = data.split("_")[1]
        products = state_manager.get_products(user_id)
        # Стиль можно запомнить, но для простоты берем дефолт
        await callback.message.delete()
        await show_dishes_for_category(callback.message, user_id, products, category, "выбранный")
        await callback.answer()
        return

    # НАЗАД К КАТЕГОРИЯМ
    if data == "back_to_categories":
        categories = state_manager.get_categories(user_id)
        if not categories:
            await callback.answer("Сессия истекла. Начните заново.")
            return
        
        await callback.message.delete()
        if len(categories) == 1:
            # Если категория одна, назад идти некуда, предлагаем рестарт или добавку
            await callback.message.answer("Категория была одна. Добавьте продукты или начните заново.", reply_markup=get_categories_keyboard(categories))
        else:
            await callback.message.answer("📂 <b>Выберите категорию:</b>", reply_markup=get_categories_keyboard(categories), parse_mode="HTML")
        await callback.answer()
        return

    # ВЫБОР БЛЮДА
    if data.startswith("dish_"):
        try:
            index = int(data.split("_")[1])
            dish_name = state_manager.get_generated_dish(user_id, index)
            products = state_manager.get_products(user_id)
            
            if not dish_name:
                await callback.answer("Меню устарело.")
                return
            
            await callback.answer("Готовлю рецепт...")
            wait = await callback.message.answer(f"👨‍🍳 Пишу рецепт: <b>{dish_name}</b>...", parse_mode="HTML")
            
            recipe = await ai_service.generate_recipe(dish_name, products)
            await wait.delete()
            
            # У старого сообщения убираем кнопки (чтобы не спамили)
            # await callback.message.edit_reply_markup(reply_markup=None) 
            
            state_manager.set_state(user_id, "recipe_sent")
            
            # ТОЛЬКО КНОПКА ВОЗВРАТА
            await callback.message.answer(recipe, reply_markup=get_recipe_back_keyboard(), parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"Dish error: {e}")
            await callback.answer("Ошибка.")
        return

def register_handlers(dp: Dispatcher):
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_author, Command("author"))
    dp.message.register(handle_direct_recipe, F.text.lower().startswith("дай рецепт"))
    dp.message.register(handle_voice, F.voice)
    dp.message.register(handle_text, F.text)
    
    dp.callback_query.register(handle_delete_msg, F.data == "delete_msg")
    dp.callback_query.register(handle_callback)