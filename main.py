import logging
import sys
import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from config import TELEGRAM_TOKEN
from handlers import register_handlers

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Инициализация
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
register_handlers(dp)

# --- МИНИ-СЕРВЕР ДЛЯ UPTIMEROBOT ---
async def health_check(request):
    """Простой эндпоинт, чтобы бот не засыпал"""
    return web.Response(text="Bot is alive!", status=200)

async def start_web_server():
    """Запуск веб-сервера на порту, который выдаст Render"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    # Render передает порт через переменную окружения PORT
    # Если переменной нет (локальный запуск), используем 8080
    port = int(os.environ.get("PORT", 8080))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌍 Web server started on port {port}")

# --- НАСТРОЙКА КОМАНД ---
async def setup_commands(bot: Bot):
    commands = [
        BotCommand(command="/start", description="🔄 Рестарт / Новые продукты"),
        BotCommand(command="/author", description="👨‍💻 Автор бота")
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception as e:
        logger.error(f"Failed to set commands: {e}")

# --- ЗАПУСК ---
async def main():
    # 1. Запускаем веб-сервер (в фоне)
    await start_web_server()
    
    # 2. Устанавливаем команды
    await setup_commands(bot)
    
    # 3. Запускаем поллинг бота (это блокирующий процесс, поэтому он последний)
    logger.info("🚀 Bot started polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")