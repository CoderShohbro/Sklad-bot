import asyncio
import logging
import uvicorn
from aiogram import Dispatcher
from backend import config, database, bot, server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("main")

async def run_bot():
    """Telegram botni ishga tushirish (polling)"""
    dp = Dispatcher()
    dp.include_router(bot.router)
    
    # Delete webhook to prevent conflicts with other bots or previous configurations
    await bot.bot.delete_webhook(drop_pending_updates=True)
    
    logger.info("Telegram Bot ishga tushmoqda...")
    try:
        await dp.start_polling(bot.bot)
    except Exception as e:
        logger.error(f"Telegram Botda xatolik yuz berdi: {e}")

async def run_server():
    """FastAPI Web serverini ishga tushirish"""
    cfg = uvicorn.Config(
        app=server.app, 
        host=config.HOST, 
        port=config.PORT, 
        log_level="info"
    )
    uvc_server = uvicorn.Server(cfg)
    logger.info(f"FastAPI Server ishga tushmoqda: http://{config.HOST}:{config.PORT}")
    try:
        await uvc_server.serve()
    except Exception as e:
        logger.error(f"FastAPI Serverda xatolik yuz berdi: {e}")

async def main():
    # 1. Ma'lumotlar bazasini initsializatsiya qilish (Jadvallar yaratish + Seed data)
    logger.info("Ma'lumotlar bazasini tekshirish va yaratish...")
    database.init_db()
    logger.info("Ma'lumotlar bazasi tayyor.")

    # 2. Bot va API Serverni bitta event loopda parallel ishga tushirish
    await asyncio.gather(
        run_bot(),
        run_server()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Tizim to'xtatildi.")
