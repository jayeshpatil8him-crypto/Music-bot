import os
import asyncio
import sys
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioPiped, AudioParameters
from youtubesearchpython import VideosSearch
import yt_dlp

print("="*50)
print("🎵 TELEGRAM MUSIC BOT - Starting...")
print("="*50)

# Get credentials
try:
    API_ID = int(os.environ['API_ID'])
    API_HASH = os.environ['API_HASH']
    BOT_TOKEN = os.environ['BOT_TOKEN']
    SESSION_STRING = os.environ['SESSION_STRING']
except:
    print("❌ ERROR: Set these in Replit Secrets:")
    print("API_ID, API_HASH, BOT_TOKEN, SESSION_STRING")
    sys.exit(1)

# Initialize clients
bot = Client(
    "music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

user = Client(
    "music_user",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

call = PyTgCalls(user)

# Store active chats
active_chats = {}

# YouTube helper
async def search_youtube(query):
    try:
        search = VideosSearch(query, limit=1)
        results = search.result().get("result", [])
        if results:
            return f"https://youtube.com/watch?v={results[0]['id']}"
    except:
        pass
    return None

async def get_stream_url(url):
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info['url']
    except:
        return None

# Bot commands
@bot.on_message(filters.command("start"))
async def start_cmd(client, message: Message):
    await message.reply_text(
        "🎵 **Music Bot Online!**\n\n"
        "**Commands:**\n"
        "/play [song] - Play in voice chat\n"
        "/stop - Stop playback\n"
        "/pause - Pause\n"
        "/resume - Resume\n"
        "/skip - Skip song\n\n"
        "**How to use:**\n"
        "1. Add me to group\n"
        "2. Give admin rights\n"
        "3. Start voice chat\n"
        "4. Use /play song_name"
    )

@bot.on_message(filters.command("play") & filters.group)
async def play_cmd(client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ Usage: /play song_name")
        return
    
    query = " ".join(message.command[1:])
    chat_id = message.chat.id
    
    msg = await message.reply_text("🔍 Searching...")
    
    # Get YouTube URL
    if "youtube.com" in query or "youtu.be" in query:
        url = query
    else:
        url = await search_youtube(query)
        if not url:
            await msg.edit_text("❌ No results found!")
            return
    
    # Get stream URL
    stream_url = await get_stream_url(url)
    if not stream_url:
        await msg.edit_text("❌ Error getting audio!")
        return
    
    await msg.edit_text("🎵 Joining voice chat...")
    
    try:
        # Create audio stream
        audio = AudioPiped(
            stream_url,
            AudioParameters.from_quality("high"),
            additional_ffmpeg_parameters="-b:a 192k"
        )
        
        # Join voice chat
        await call.join_group_call(chat_id, audio)
        active_chats[chat_id] = True
        
        await msg.edit_text("✅ Playing music in voice chat!")
        
    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)}")

@bot.on_message(filters.command("stop"))
async def stop_cmd(client, message: Message):
    chat_id = message.chat.id
    try:
        await call.leave_group_call(chat_id)
        active_chats.pop(chat_id, None)
        await message.reply_text("🛑 Stopped playback")
    except:
        await message.reply_text("❌ Not playing!")

@bot.on_message(filters.command("pause"))
async def pause_cmd(client, message: Message):
    chat_id = message.chat.id
    try:
        await call.pause_stream(chat_id)
        await message.reply_text("⏸ Paused")
    except:
        await message.reply_text("❌ Error!")

@bot.on_message(filters.command("resume"))
async def resume_cmd(client, message: Message):
    chat_id = message.chat.id
    try:
        await call.resume_stream(chat_id)
        await message.reply_text("▶️ Resumed")
    except:
        await message.reply_text("❌ Error!")

@bot.on_message(filters.command("skip"))
async def skip_cmd(client, message: Message):
    await message.reply_text("⏭ Skipped current song")
    # You can add logic to play next in queue

@bot.on_message(filters.command("ping"))
async def ping_cmd(client, message: Message):
    await message.reply_text("🏓 Pong! Bot is alive")

# Keep-alive server
from flask import Flask
from threading import Thread

flask_app = Flask('')
@flask_app.route('/')
def home(): return "Music Bot Online"
def run_flask(): flask_app.run(host='0.0.0.0', port=8080)
Thread(target=run_flask, daemon=True).start()

# Main function
async def main():
    print("🚀 Starting Telegram clients...")
    
    try:
        # Start clients
        await user.start()
        print("✅ User client started")
        
        await bot.start()
        me = await bot.get_me()
        print(f"✅ Bot started: @{me.username}")
        
        await call.start()
        print("✅ Voice chat client ready")
        
        print("\n" + "="*50)
        print("🎵 BOT IS READY!")
        print("="*50)
        print("\nAdd to group and use /play [song]")
        
        # Keep running
        await idle()
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
    finally:
        await bot.stop()
        await user.stop()

if __name__ == "__main__":
    asyncio.run(main())
