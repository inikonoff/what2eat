import aiohttp
import json
import logging
from typing import List, Dict
from config import YANDEX_API_KEY, YANDEX_FOLDER_ID

GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"

class YandexService:
    # --- SPEECH KIT ---
    @staticmethod
    async def speech_to_text(audio_bytes: bytes) -> str:
        headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}"}
        params = {"lang": "ru-RU", "format": "oggopus", "topic": "general"}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(STT_URL, params=params, headers=headers, data=audio_bytes) as resp:
                    if resp.status != 200: return ""
                    result = await resp.json()
                    return result.get("result", "")
            except Exception:
                return ""

    # --- GPT BASE ---
    @staticmethod
    async def _send_gpt_request(system_prompt: str, user_text: str, temperature: float = 0.5, max_tokens: int = 1500) -> str:
        headers = {
            "Authorization": f"Api-Key {YANDEX_API_KEY}",
            "x-folder-id": YANDEX_FOLDER_ID,
            "Content-Type": "application/json"
        }
        body = {
            "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
            "completionOptions": {"stream": False, "temperature": temperature, "maxTokens": max_tokens},
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": user_text}
            ]
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(GPT_URL, headers=headers, json=body) as resp:
                    if resp.status != 200:
                        logging.error(f"GPT Error {resp.status}: {await resp.text()}")
                        return ""
                    result = await resp.json()
                    return result['result']['alternatives'][0]['message']['text']
            except Exception as e:
                logging.error(f"Request Error: {e}")
                return ""

    # --- АНАЛИЗ КАТЕГОРИЙ ---
    @staticmethod
    async def analyze_categories(products: str) -> List[str]:
        prompt = f"""Ты опытный шеф-повар. Проанализируй список продуктов: "{products}".
        Определи, какие категории блюд из этого РЕАЛЬНО приготовить (имея базовые соль/воду/масло).
        Возможные категории: "soup", "main", "salad", "breakfast", "dessert", "drink", "snack".
        ВЕРНИ ТОЛЬКО JSON список ключей. Пример: ["main", "salad"]
        """
        res = await YandexService._send_gpt_request(prompt, "Анализируй категории", 0.3)
        try:
            clean_json = res.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            if isinstance(data, list): return data
        except: pass
        return ["main"]

    # --- ГЕНЕРАЦИЯ СПИСКА БЛЮД ---
    @staticmethod
    async def generate_dishes_list(products: str, category: str, style: str = "обычный") -> List[Dict[str, str]]:
        cat_names = {
            "soup": "Супы", "main": "Вторые блюда", "salad": "Салаты",
            "breakfast": "Завтраки", "dessert": "Десерты", "drink": "Напитки", "snack": "Закуски"
        }
        cat_ru = cat_names.get(category, "Блюда")

        prompt = f"""Ты шеф-повар. Продукты: {products}.
        Задача: Придумай 5-6 разнообразных блюд в категории: "{cat_ru}". Стиль: {style}.
        ВЕРНИ СТРОГО JSON формат:
        [
            {{"name": "Название", "desc": "Краткое описание"}}
        ]
        """
        res = await YandexService._send_gpt_request(prompt, "Предложи меню JSON", 0.5)
        try:
            clean_json = res.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            if isinstance(data, list): return data
        except Exception: pass
        return []

    # --- ВСПОМОГАТЕЛЬНЫЕ ---
    @staticmethod
    async def validate_ingredients(text: str) -> bool:
        prompt = """Твоя задача — модерация. Верни JSON: {"valid": true} если это съедобные продукты. Иначе false."""
        res = await YandexService._send_gpt_request(prompt, f"Анализируй: \"{text}\"", 0.1)
        return "true" in res.lower()

    @staticmethod
    async def determine_intent(user_message: str, dish_list_text: str) -> dict:
        prompt = f"""Контекст: {dish_list_text}
        Сообщение: "{user_message}"
        Intent: "add_products" или "select_dish".
        JSON: {{"intent": "...", "products": "...", "dish_name": "..."}}"""
        res = await YandexService._send_gpt_request(prompt, "Анализируй", 0.1)
        try:
            start, end = res.find('{'), res.rfind('}')
            if start != -1: return json.loads(res[start:end+1])
        except: pass
        return {"intent": "unclear"}

    # --- ОБНОВЛЕННАЯ ГЕНЕРАЦИЯ РЕЦЕПТА (С ТРИАДОЙ) ---
    @staticmethod
    async def generate_recipe(dish_name: str, products: str) -> str:
        prompt = f"""Напиши подробный рецепт: "{dish_name}".
        Имеющиеся продукты: {products} (можно добавлять соль, перец, сахар, подсолнечное масло, лёд и воду по умолчанию).
        
        СТРУКТУРА ОТВЕТА:
        1. 🍽️ [Название блюда]
        2. 🛒 Ингредиенты (с граммовками)
        3. 👨‍🍳 Приготовление (по шагам)
        
        4. 🎓 СОВЕТ ШЕФА (Кулинарная триада):
        Проанализируй полученное блюдо на баланс вкусов (Жирное, Кислое, Соленое, Сладкое, Острое) и текстур (Мягкое/Хрустящее).
        Напиши короткий совет: чего не хватает для идеала в контексте кулинарной триады? Порекомендуй ТОЛЬКО ОДИН ингредиент!
        Пример: "Блюдо вышло жирным и мягким. Добавьте для баланса маринованный лук (кислота/хруст) или подайте с долькой лимона."
        """
        
        res = await YandexService._send_gpt_request(prompt, "Напиши рецепт с советом", 0.4)
        if YandexService._is_refusal(res): return res
        return res + "\n\n👨‍🍳 <b>Приятного аппетита!</b>"

    @staticmethod
    async def generate_freestyle_recipe(dish_name: str) -> str:
        # Тоже добавляем триаду для прямых запросов "Дай рецепт Х"
        prompt = f"""Рецепт: "{dish_name}". 
        Стиль: Креативный, но понятный.
        
        В конце обязательно добавь блок:
        🎓 СОВЕТ ПО БАЛАНСУ ВКУСОВ (какой ОДИН ИНГРЕДИЕНТ добавить для контраста текстуры, вкуса или кислотности в рамках концепции кулинарной триады).
        """
        res = await YandexService._send_gpt_request(prompt, "Напиши рецепт", 0.6)
        if YandexService._is_refusal(res): return res
        return res + "\n\n👨‍🍳 <b>Приятного аппетита!</b>"
        
    @staticmethod
    def _is_refusal(text: str) -> bool:
        if "⛔" in text: return True
        refusals = ["не могу обсуждать", "поговорим о чём-нибудь ещё", "я не могу ответить", "нарушает правила"]
        for ph in refusals:
            if ph in text.lower(): return True
        return False