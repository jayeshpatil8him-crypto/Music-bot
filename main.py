import os
import asyncio
import logging
import sys
from collections import deque
from typing import Dict, List, Optional
from threading import Thread
import time
import requests

# ========== CONFIGURATION ==========
# Get from Replit Secrets
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")

# Bot settings (optimized for Replit)
MAX_QUEUE_SIZE = 30  # Lower for Replit memory
AUDIO_QUALITY = "192k"  # Medium quality
DEFAULT_VOLUME = 70

# ========== VALIDATE ==========
if not all([API_ID, API_HASH, BOT_TOKEN, SESSION_STRING]):
    print("❌ ERROR: Set these in Replit Secrets (lock icon):")
    print("1. API_ID and API_HASH from https://my.telegram.org")
    print("2. BOT_TOKEN from @BotFather")
    print("3. SESSION_STRING (generate with script below)")
    print("\nTo generate SESSION_STRING, run on your computer:")
    print('python -c "from pyrogram import Client; print(Client(\'session\', api_id=YOUR_ID, api_hash=\'YOUR_HASH\').export_session_string())"')
    sys.exit(1)

# ========== LOGGING ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# ========== GLOBAL VARIABLES ==========
queues: Dict[int, deque] = {}
now_playing: Dict[int, Dict] = {}
loop_mode: Dict[int, bool] = {}
user_volumes: Dict[int, int] = {}

# ========== IMPORTS ==========
try:
    from pyrogram import Client, filters, idle
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
    from pyrogram.enums import ParseMode
    from pytgcalls import PyTgCalls
    from pytgcalls.types import AudioPiped, AudioParameters
    from youtubesearchpython import VideosSearch
    import yt_dlp
except ImportError:
    print("❌ Missing dependencies! Run: pip install -r requirements.txt")
    sys.exit(1)

# ========== KEEP-ALIVE SERVER ==========
from flask import Flask
web_app = Flask('')

@web_app.route('/')
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>🎵 Music Bot</title>
        <meta http-equiv="refresh" content="300">
        <style>
            body {font-family: Arial; text-align: center; padding: 50px;}
            .online {color: green; font-size: 24px;}
        </style>
    </head>
    <body>
        <h1>🎵 Telegram Music Bot</h1>
        <div class="online">✅ ONLINE</div>
        <p>Running on Replit</p>
        <p>URL will auto-refresh to keep bot alive</p>
    </html>
    """

@web_app.route('/health')
def health():
    return "OK"

def run_web():
    web_app.run(host='0.0.0.0', port=8080)

def ping_self():
    """Ping own URL to prevent sleep"""
    while True:
        try:
            repl_url = f"https://{os.getenv('REPL_SLUG')}.{os.getenv('REPL_OWNER')}.repl.co"
            requests.get(repl_url, timeout=10)
        except:
            try:
                requests.get("http://localhost:8080", timeout=10)
            except:
                pass
        time.sleep(240)  # Ping every 4 minutes

# ========== INITIALIZE CLIENTS ==========
bot = Client(
    "music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    parse_mode=ParseMode.MARKDOWN
)

user_client = Client(
    "music_user",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

call = PyTgCalls(user_client)

# ========== HELPER FUNCTIONS ==========
def get_queue(chat_id: int) -> deque:
    if chat_id not in queues:
        queues[chat_id] = deque(maxlen=MAX_QUEUE_SIZE)
    return queues[chat_id]

async def search_youtube(query: str, limit: int = 5) -> List[Dict]:
    try:
        search = VideosSearch(query, limit=limit)
        results = search.result().get("result", [])
        return results[:limit]
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []

async def get_song_info(url: str) -> Optional[Dict]:
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Get audio stream URL
            formats = info.get('formats', [])
            audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
            
            if audio_formats:
                audio_formats.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                stream_url = audio_formats[0]['url']
            else:
                stream_url = info.get('url', '')
            
            return {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'stream_url': stream_url,
                'thumbnail': info.get('thumbnail'),
                'youtube_url': info.get('webpage_url'),
                'channel': info.get('channel', 'Unknown'),
            }
    except Exception as e:
        logger.error(f"Error getting song: {e}")
        return None

def format_time(seconds: int) -> str:
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"

async def play_next(chat_id: int):
    queue = get_queue(chat_id)
    
    # Loop mode
    if loop_mode.get(chat_id, False) and chat_id in now_playing:
        await play_song(chat_id, now_playing[chat_id])
        return
    
    # Next song
    if queue:
        song = queue.popleft()
        await play_song(chat_id, song)
    else:
        now_playing.pop(chat_id, None)
        await bot.send_message(chat_id, "✅ Queue finished!")

async def play_song(chat_id: int, song: Dict):
    try:
        now_playing[chat_id] = song
        
        # Create audio stream
        audio_stream = AudioPiped(
            song['stream_url'],
            AudioParameters.from_quality("medium"),
            additional_ffmpeg_parameters=f"-b:a {AUDIO_QUALITY}"
        )
        
        # Set volume
        volume = user_volumes.get(chat_id, DEFAULT_VOLUME)
        
        # Join or change stream
        try:
            await call.join_group_call(chat_id, audio_stream)
        except:
            await call.change_stream(chat_id, audio_stream)
        
        await call.set_my_volume(chat_id, volume)
        
        # Send message
        duration = format_time(song.get('duration', 0))
        text = f"🎵 **Now Playing:** {song['title']}\n⏰ **Duration:** {duration}\n👤 **Channel:** {song.get('channel', 'Unknown')}"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏸ Pause", callback_data="pause"), InlineKeyboardButton("▶️ Resume", callback_data="resume")],
            [InlineKeyboardButton("⏭ Skip", callback_data="skip"), InlineKeyboardButton("🔁 Loop", callback_data="loop")],
            [InlineKeyboardButton("📋 Queue", callback_data="queue"), InlineKeyboardButton("❌ Stop", callback_data="stop")]
        ])
        
        await bot.send_message(chat_id, text, reply_markup=keyboard)
        logger.info(f"Playing: {song['title']}")
        
    except Exception as e:
        logger.error(f"Play error: {e}")
        await bot.send_message(chat_id, f"❌ Error: {str(e)}")
        await play_next(chat_id)

# ========== COMMAND HANDLERS ==========
@bot.on_message(filters.command("start"))
async def start_cmd(client: Client, message: Message):
    await message.reply_text(
        "🎵 **Music Bot Online!**\n\n"
        "**Commands:**\n"
        "• /play [song] - Play music\n"
        "• /splay [query] - Search & play\n"
        "• /queue - Show queue\n"
        "• /pause - Pause\n"
        "• /resume - Resume\n"
        "• /skip - Skip song\n"
        "• /stop - Stop all\n"
        "• /loop - Toggle loop\n"
        "• /volume [1-200] - Set volume\n"
        "• /clear - Clear queue\n\n"
        "**Tip:** Add songs to queue by using /play when music is already playing!"
    )

@bot.on_message(filters.command("play") & filters.group)
async def play_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ Usage: /play song_name")
        return
    
    query = " ".join(message.command[1:])
    chat_id = message.chat.id
    msg = await message.reply_text("🔍 Searching...")
    
    # Check if URL or search
    if "youtube.com" in query or "youtu.be" in query:
        url = query
    else:
        results = await search_youtube(query, limit=1)
        if not results:
            await msg.edit_text("❌ No results found!")
            return
        url = f"https://youtube.com/watch?v={results[0]['id']}"
    
    # Get song info
    song = await get_song_info(url)
    if not song:
        await msg.edit_text("❌ Error getting song!")
        return
    
    # Check if already playing
    if chat_id in now_playing:
        queue = get_queue(chat_id)
        if len(queue) >= MAX_QUEUE_SIZE:
            await msg.edit_text(f"❌ Queue full! Max {MAX_QUEUE_SIZE} songs.")
            return
        
        queue.append(song)
        await msg.edit_text(f"✅ **Added to queue:** {song['title']}\nPosition: #{len(queue)}")
    else:
        await msg.edit_text("🎵 Playing...")
        await play_song(chat_id, song)

@bot.on_message(filters.command("splay") & filters.group)
async def splay_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ Usage: /splay search_query")
        return
    
    query = " ".join(message.command[1:])
    msg = await message.reply_text(f"🔍 Searching: {query}")
    
    results = await search_youtube(query, limit=5)
    
    if not results:
        await msg.edit_text("❌ No results found!")
        return
    
    # Create buttons
    buttons = []
    for i, result in enumerate(results):
        title = result['title'][:35] + "..." if len(result['title']) > 35 else result['title']
        duration = result.get('duration', 'N/A')
        buttons.append([
            InlineKeyboardButton(f"{i+1}. {title} ({duration})", callback_data=f"play_{result['id']}")
        ])
    
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    
    await msg.edit_text(
        "🎵 **Search Results:**\nSelect a song to play:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@bot.on_message(filters.command("queue"))
async def queue_cmd(client: Client, message: Message):
    chat_id = message.chat.id
    queue = get_queue(chat_id)
    
    if not queue and chat_id not in now_playing:
        await message.reply_text("🎶 Queue is empty!")
        return
    
    text = "📋 **Current Queue:**\n\n"
    
    if chat_id in now_playing:
        current = now_playing[chat_id]
        duration = format_time(current.get('duration', 0))
        text += f"🎵 **Now Playing:** {current['title']} ({duration})\n\n"
    
    if queue:
        text += "**Up Next:**\n"
        for i, song in enumerate(queue[:10], 1):
            duration = format_time(song.get('duration', 0))
            text += f"{i}. {song['title']} ({duration})\n"
        
        if len(queue) > 10:
            text += f"\n... and {len(queue) - 10} more songs"
        
        text += f"\n**Total:** {len(queue)} songs"
    
    await message.reply_text(text)

@bot.on_message(filters.command(["pause", "resume", "skip", "stop"]))
async def control_cmd(client: Client, message: Message):
    chat_id = message.chat.id
    cmd = message.command[0]
    
    try:
        if cmd == "pause":
            await call.pause_stream(chat_id)
            await message.reply_text("⏸ Playback paused")
        elif cmd == "resume":
            await call.resume_stream(chat_id)
            await message.reply_text("▶️ Playback resumed")
        elif cmd == "skip":
            if chat_id in now_playing:
                await message.reply_text("⏭ Skipping...")
                await play_next(chat_id)
            else:
                await message.reply_text("❌ Nothing is playing!")
        elif cmd == "stop":
            await call.leave_group_call(chat_id)
            if chat_id in queues:
                queues[chat_id].clear()
            now_playing.pop(chat_id, None)
            await message.reply_text("🛑 Playback stopped")
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")

@bot.on_message(filters.command("loop"))
async def loop_cmd(client: Client, message: Message):
    chat_id = message.chat.id
    loop_mode[chat_id] = not loop_mode.get(chat_id, False)
    status = "ON" if loop_mode[chat_id] else "OFF"
    await message.reply_text(f"🔁 Loop mode: **{status}**")

@bot.on_message(filters.command("volume"))
async def volume_cmd(client: Client, message: Message):
    if len(message.command) != 2:
        await message.reply_text("❌ Usage: /volume 1-200\nExample: /volume 80")
        return
    
    try:
        vol = int(message.command[1])
        if 1 <= vol <= 200:
            chat_id = message.chat.id
            user_volumes[chat_id] = vol
            try:
                await call.set_my_volume(chat_id, vol)
                await message.reply_text(f"🔊 Volume set to {vol}%")
            except:
                await message.reply_text(f"🔊 Volume will be {vol}% on next song")
        else:
            await message.reply_text("❌ Volume must be between 1 and 200")
    except ValueError:
        await message.reply_text("❌ Please enter a valid number!")

@bot.on_message(filters.command("clear"))
async def clear_cmd(client: Client, message: Message):
    chat_id = message.chat.id
    queue = get_queue(chat_id)
    if queue:
        queue.clear()
        await message.reply_text("🗑 Queue cleared!")
    else:
        await message.reply_text("❌ Queue is already empty!")

@bot.on_message(filters.command("help"))
async def help_cmd(client: Client, message: Message):
    await message.reply_text(
        "**🎵 Music Bot Help**\n\n"
        "**To add songs to queue:**\n"
        "1. First song: /play song1\n"
        "2. Second song: /play song2 (adds to queue)\n"
        "3. Third song: /play song3 (adds to queue)\n\n"
        "**Commands:**\n"
        "/play [song] - Play or add to queue\n"
        "/splay [query] - Search & play\n"
        "/queue - Show queue\n"
        "/pause - Pause\n"
        "/resume - Resume\n"
        "/skip - Skip\n"
        "/stop - Stop all\n"
        "/loop - Toggle loop\n"
        "/volume [1-200] - Volume\n"
        "/clear - Clear queue\n\n"
        "**Need help?** DM me!"
    )

# ========== CALLBACK HANDLER ==========
@bot.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    chat_id = callback_query.message.chat.id
    data = callback_query.data
    
    try:
        if data == "pause":
            await call.pause_stream(chat_id)
            await callback_query.answer("⏸ Paused")
        elif data == "resume":
            await call.resume_stream(chat_id)
            await callback_query.answer("▶️ Resumed")
        elif data == "skip":
            if chat_id in now_playing:
                await callback_query.answer("⏭ Skipping...")
                await play_next(chat_id)
            else:
                await callback_query.answer("❌ Nothing playing!")
        elif data == "loop":
            loop_mode[chat_id] = not loop_mode.get(chat_id, False)
            status = "ON" if loop_mode[chat_id] else "OFF"
            await callback_query.answer(f"🔁 Loop: {status}")
        elif data == "stop":
            await call.leave_group_call(chat_id)
            if chat_id in queues:
                queues[chat_id].clear()
            now_playing.pop(chat_id, None)
            await callback_query.answer("🛑 Stopped")
            await callback_query.message.delete()
        elif data == "queue":
            await queue_cmd(client, callback_query.message)
            await callback_query.answer()
        elif data.startswith("play_"):
            video_id = data.split("_")[1]
            url = f"https://youtube.com/watch?v={video_id}"
            await callback_query.answer("🎵 Loading...")
            
            song = await get_song_info(url)
            if song:
                if chat_id in now_playing:
                    queue = get_queue(chat_id)
                    queue.append(song)
                    await callback_query.message.edit_text(f"✅ Added: {song['title']}")
                else:
                    await callback_query.message.delete()
                    await play_song(chat_id, song)
        elif data == "cancel":
            await callback_query.message.delete()
            await callback_query.answer("❌ Cancelled")
    except Exception as e:
        logger.error(f"Callback error: {e}")
        await callback_query.answer("❌ Error!")

# ========== EVENT HANDLERS ==========
@call.on_stream_end()
async def stream_end(chat_id: int):
    logger.info(f"Stream ended in {chat_id}")
    await play_next(chat_id)

# ========== MAIN FUNCTION ==========
async def main():
    logger.info("🚀 Starting Music Bot on Replit...")
    
    # Start keep-alive threads
    web_thread = Thread(target=run_web, daemon=True)
    web_thread.start()
    
    ping_thread = Thread(target=ping_self, daemon=True)
    ping_thread.start()
    
    logger.info("🌐 Web server started on port 8080")
    logger.info("🔄 Auto-ping enabled for 24/7")
    
    try:
        # Start Telegram clients
        await user_client.start()
        await bot.start()
        await call.start()
        
        me = await bot.get_me()
        logger.info(f"✅ Bot ready: @{me.username}")
        logger.info("🎵 Audio quality: " + AUDIO_QUALITY)
        logger.info("📊 Max queue: " + str(MAX_QUEUE_SIZE))
        
        # Keep running
        await idle()
        
    except Exception as e:
        logger.error(f"❌ Failed to start: {e}")
    finally:
        await bot.stop()
        await user_client.stop()

if __name__ == "__main__":
    asyncio.run(main())
