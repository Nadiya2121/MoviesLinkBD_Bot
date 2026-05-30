# main.py
import asyncio
import uvicorn
from fastapi.middleware.cors import CORSMiddleware

from config import (
    app, dp, bot, pyro_app, PORT_NUMBER, logger, db,
    load_admins, load_banned_users, load_keyword_replies
)
from helpers import cleanup_temp_files
from api.routes import api_router

# বটের হ্যান্ডলারসমূহ এবং ব্যাকগ্রাউন্ড ওয়ার্কার লোড করা হলো (রেজিস্ট্রেশনের জন্য)
import bot.handlers
from bot.workers import video_queue_worker, auto_delete_worker

# CORS মিডেলওয়্যার কনফিগারেশন
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# এপিআই রাউটারসমূহ রেজিস্টার করা হলো
app.include_router(api_router)

# আপকামিং রাউটারটি নিরাপদ উপায়ে রেজিস্টার করা হলো
try:
    from upcoming_router import upcoming_router
    app.include_router(upcoming_router)
    logger.info("Upcoming router registered successfully.")
except ImportError:
    logger.warning("upcoming_router.py not found. Bypassing upcoming_router setup.")

# কাস্টম ইউভিকর্ন সার্ভার যা সিগন্যাল হাইজ্যাক হওয়া প্রতিরোধ করে
class CustomUvicornServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        pass

# ডাটাবেস ইনডেক্সিং এবং ইনিশিয়ালাইজেশন
async def init_db():
    await db.movies.create_index([("title", "text")])
    await db.movies.create_index("created_at")
    await db.auto_delete.create_index("delete_at")
    try:
        await db.payments.create_index("trx_id", unique=True)
    except Exception: pass
    await db.ads.create_index("expires_at")
    
    await db.movie_views.create_index([("title", 1), ("viewed_at", -1)])
    try:
        await db.movie_views.create_index("viewed_at", expireAfterSeconds=2592000) 
    except Exception: pass

# স্টার্টআপ ফাংশন
async def start():
    cleanup_temp_files()
    
    try:
        await init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        
    try:
        await load_admins()
        await load_banned_users()
        await load_keyword_replies()
        logger.info("Cache configurations loaded successfully.")
    except Exception as e:
        logger.error(f"Caches failed to load properly: {e}")

    # ইউভিকর্ন রান কনফিগারেশন
    config = uvicorn.Config(
        app, 
        host="0.0.0.0", 
        port=PORT_NUMBER, 
        loop="asyncio"
    )
    
    server = CustomUvicornServer(config)
    
    # পাইরোগ্রাম ক্লায়েন্ট চালু করা হচ্ছে
    try:
        await pyro_app.start()
        logger.info("Pyrogram client started successfully.")
    except Exception as e:
        logger.error(f"Pyrogram start-up bypassed or errored: {e}. Media functions may use fallback tasks.")
        
    # ব্যাকগ্রাউন্ড টাস্কসমূহ চালু করা হচ্ছে
    asyncio.create_task(auto_delete_worker())
    asyncio.create_task(video_queue_worker()) 
    
    # পেন্ডিং টেলিগ্রাম আপডেটসমূহ ক্লিয়ার করা হচ্ছে
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Failed to clear webhook configurations: {e}")
        
    # FastAPI সার্ভার ব্যাকগ্রাউন্ডে রান করা হচ্ছে
    asyncio.create_task(server.serve())
    logger.info("FastAPI Uvicorn running concurrently...")
    
    # টেলিগ্রাম বট লং-পোলিং স্টার্ট করা হলো
    logger.info("Bot polling initiated.")
    await dp.start_polling(bot)

if __name__ == "__main__": 
    try: 
        asyncio.run(start())
    except (KeyboardInterrupt, SystemExit): 
        logger.info("App shutdown gracefully.")
