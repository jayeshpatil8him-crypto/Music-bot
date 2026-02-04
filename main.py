import os
import sys
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioPiped, AudioParameters

# Add Replit-specific imports
from keep_alive import keep_alive

# Configure logging for Replit
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# Get environment variables from Replit Secrets
API_ID = int(os.environ.get("API_ID", "12345678"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")

# Initialize clients
bot = Client(
    "music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins")
)

user_client = Client(
    "music_user",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

call = PyTgCalls(user_client)

# Store active voice chats
active_chats = {}

@bot.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    await message.reply_text(
        "🎵 **Music Bot Online!**\n\n"
        "I'm running on Replit with 24/7 uptime!\n\n"
        "Commands:\n"
        "/play [song] - Play music\n"
        "/ping - Check bot status\n"
        "/stats - View bot stats\n\n"
        "🔗 GitHub: https://github.com/yourusername/telegram-music-bot"
    )

@bot.on_message(filters.command("play") & filters.group)
async def play_command(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /play song_name")
        return
    
    # Join voice chat and play music logic here
    # (Use code from previous implementations)
    await message.reply_text("Playing music...")

@bot.on_message(filters.command("ping"))
async def ping_command(client: Client, message: Message):
    import time
    start = time.time()
    msg = await message.reply_text("🏓 Pong!")
    end = time.time()
    await msg.edit_text(f"🏓 Pong! `{round((end - start) * 1000, 2)}ms`")

@bot.on_message(filters.command("stats"))
async def stats_command(client: Client, message: Message):
    import psutil
    import platform
    
    # Get system stats
    cpu_usage = psutil.cpu_percent()
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    stats_text = f"""
**🤖 Bot Statistics:**
    
**System Info:**
• OS: {platform.system()} {platform.release()}
• Python: {platform.python_version()}
• Uptime: {get_uptime()}
    
**Resource Usage:**
• CPU: {cpu_usage}%
• RAM: {memory.percent}% ({memory.used // (1024 ** 2)}MB/{memory.total // (1024 ** 2)}MB)
• Disk: {disk.percent}% ({disk.used // (1024 ** 3)}GB/{disk.total // (1024 ** 3)}GB)
    
**Bot Info:**
• Active Chats: {len(active_chats)}
• Replit URL: https://{os.environ.get('REPL_SLUG')}.{os.environ.get('REPL_OWNER')}.repl.co
    """
    
    await message.reply_text(stats_text)

def get_uptime():
    import time
    uptime_seconds = time.time() - psutil.boot_time()
    days, remainder = divmod(int(uptime_seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours}h {minutes}m {seconds}s"

# Web server for health checks
from fastapi import FastAPI
import uvicorn
from threading import Thread

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "online", "service": "telegram-music-bot"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": time.time()}

@app.get("/stats")
async def api_stats():
    import psutil
    return {
        "cpu": psutil.cpu_percent(),
        "memory": psutil.virtual_memory().percent,
        "active_chats": len(active_chats)
    }

def run_web_server():
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")

async def main():
    # Start the web server in a separate thread
    web_thread = Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    # Start the keep_alive server
    keep_alive()
    
    # Start Telegram clients
    await bot.start()
    await user_client.start()
    await call.start()
    
    logger.info("🤖 Bot started successfully on Replit!")
    
    # Send startup notification
    me = await bot.get_me()
    logger.info(f"Bot username: @{me.username}")
    
    # Keep the bot running
    await idle()

if __name__ == "__main__":
    # Start the bot
    asyncio.run(main())
