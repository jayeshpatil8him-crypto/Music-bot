import os
import asyncio
import logging
import sys
from collections import deque
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Load environment variables FIRST
load_dotenv()

# Telegram imports
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ParseMode
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioPiped, AudioParameters
from pytgcalls.exceptions import GroupCallNotFound, NoActiveGroupCall

# YouTube imports
from youtubesearchpython import VideosSearch
import yt_dlp

# ========== CONFIGURATION ==========
# Get values from .env file
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")

# Bot settings
MAX_QUEUE_SIZE = 100
AUDIO_QUALITY = "320k"
DEFAULT_VOLUME = 80

# ========== VALIDATE CREDENTIALS ==========
if not all([API_ID, API_HASH, BOT_TOKEN, SESSION_STRING]):
    print("❌ ERROR: Missing credentials in .env file!")
    print("Please fill in:")
    print("1. API_ID and API_HASH from https://my.telegram.org")
    print("2. BOT_TOKEN from @BotFather")
    print("3. SESSION_STRING (generate with script below)")
    print("\nTo generate SESSION_STRING, run:")
    print('python -c "from pyrogram import Client; print(Client(\'session\', api_id=YOUR_API_ID, api_hash=\'YOUR_API_HASH\').export_session_string())"')
    sys.exit(1)

# ========== LOGGING ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== GLOBAL VARIABLES ==========
queues: Dict[int, deque] = {}
now_playing: Dict[int, Dict] = {}
loop_mode: Dict[int, bool] = {}
user_volumes: Dict[int, int] = {}

# ========== INITIALIZE CLIENTS ==========
# Bot client (for receiving commands)
bot = Client(
    name="music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    parse_mode=ParseMode.MARKDOWN
)

# User client (for PyTgCalls - needs session string)
user_client = Client(
    name="music_user",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# Initialize PyTgCalls for voice chat
call = PyTgCalls(user_client)

# ========== HELPER FUNCTIONS ==========
def get_queue(chat_id: int) -> deque:
    """Get or create queue for chat"""
    if chat_id not in queues:
        queues[chat_id] = deque(maxlen=MAX_QUEUE_SIZE)
    return queues[chat_id]

async def search_youtube(query: str, limit: int = 5) -> List[Dict]:
    """Search YouTube videos"""
    try:
        search = VideosSearch(query, limit=limit)
        results = search.result().get("result", [])
        return results[:limit]
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []

async def get_youtube_stream_url(url: str) -> Optional[Dict]:
    """Get audio stream URL from YouTube"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Find best audio format
            formats = info.get('formats', [])
            audio_formats = [
                f for f in formats 
                if f.get('acodec') != 'none' and f.get('vcodec') == 'none'
            ]
            
            if audio_formats:
                # Get highest quality
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
                'view_count': info.get('view_count', 0)
            }
    except Exception as e:
        logger.error(f"Error getting YouTube stream: {e}")
        return None

def format_duration(seconds: int) -> str:
    """Format seconds to HH:MM:SS or MM:SS"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

async def play_next(chat_id: int):
    """Play next song in queue"""
    queue = get_queue(chat_id)
    
    # Check loop mode
    if loop_mode.get(chat_id, False) and chat_id in now_playing:
        # Play current song again
        await play_song(chat_id, now_playing[chat_id])
        return
    
    # Get next song from queue
    if queue:
        song = queue.popleft()
        await play_song(chat_id, song)
    else:
        # No more songs
        now_playing.pop(chat_id, None)
        await bot.send_message(chat_id, "✅ Queue finished!")

async def play_song(chat_id: int, song: Dict):
    """Play a song in voice chat"""
    try:
        # Update now playing
        now_playing[chat_id] = song
        
        # Create high-quality audio stream
        audio_stream = AudioPiped(
            song['stream_url'],
            AudioParameters.from_quality("high"),
            additional_ffmpeg_parameters=f"-b:a {AUDIO_QUALITY}"
        )
        
        # Set volume
        volume_level = user_volumes.get(chat_id, DEFAULT_VOLUME)
        
        # Join call if not already joined
        try:
            await call.join_group_call(chat_id, audio_stream)
        except (GroupCallNotFound, NoActiveGroupCall):
            await bot.send_message(chat_id, "❌ No active voice chat! Start one and invite me.")
            return
        except Exception:
            # Already in call, just change stream
            await call.change_stream(chat_id, audio_stream)
        
        # Set volume
        await call.set_my_volume(chat_id, volume_level)
        
        # Send now playing message
        duration = format_duration(song.get('duration', 0))
        
        caption = f"""
🎵 **Now Playing:** {song['title']}
⏰ **Duration:** {duration}
👤 **Channel:** {song.get('channel', 'Unknown')}
🔗 [Watch on YouTube]({song.get('youtube_url', '')})

Use buttons below to control playback!
        """
        
        # Create control buttons
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⏸ Pause", callback_data="pause"),
                InlineKeyboardButton("▶️ Resume", callback_data="resume")
            ],
            [
                InlineKeyboardButton("⏭ Skip", callback_data="skip"),
                InlineKeyboardButton("🔁 Loop", callback_data="loop")
            ],
            [
                InlineKeyboardButton("📋 Queue", callback_data="show_queue"),
                InlineKeyboardButton("🔊 Volume", callback_data="volume_menu")
            ],
            [
                InlineKeyboardButton("❌ Stop", callback_data="stop")
            ]
        ])
        
        # Send message
        try:
            if song.get('thumbnail'):
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=song['thumbnail'],
                    caption=caption,
                    reply_markup=keyboard
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    reply_markup=keyboard
                )
        except:
            await bot.send_message(
                chat_id=chat_id,
                text=caption,
                reply_markup=keyboard
            )
        
        logger.info(f"Playing: {song['title']} in chat {chat_id}")
        
    except Exception as e:
        logger.error(f"Play error: {e}")
        await bot.send_message(chat_id, f"❌ Error playing song: {str(e)}")
        await play_next(chat_id)

# ========== COMMAND HANDLERS ==========
@bot.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    """Start command"""
    await message.reply_text(
        f"""
🎵 **Welcome to Music Bot!**

I can play high-quality music in Telegram voice chats from YouTube.

**✨ Features:**
• High-quality {AUDIO_QUALITY} audio
• YouTube search and playback
• Queue system ({MAX_QUEUE_SIZE} songs)
• Loop mode
• Volume control

**🎛️ Commands:**
/play [song/URL] - Play a song
/splay [query] - Search and play
/queue - Show current queue
/pause - Pause playback
/resume - Resume playback
/skip - Skip current song
/stop - Stop playback
/loop - Toggle loop mode
/volume [1-200] - Set volume
/clear - Clear queue
/nowplaying - Show current song
/help - Show help

**🎯 Quick start:**
1. Add me to your group
2. Give me admin rights
3. Start a voice chat
4. Use /play [song] to start!
        """
    )

@bot.on_message(filters.command("play") & filters.group)
async def play_command(client: Client, message: Message):
    """Play a song"""
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide a song name or YouTube URL!\nExample: `/play never gonna give you up`")
        return
    
    query = " ".join(message.command[1:])
    chat_id = message.chat.id
    
    # Send processing message
    processing_msg = await message.reply_text("🔍 Searching...")
    
    # Check if it's a URL or search query
    if "youtube.com" in query or "youtu.be" in query:
        url = query
    else:
        # Search YouTube
        results = await search_youtube(query, limit=1)
        if not results:
            await processing_msg.edit_text("❌ No results found!")
            return
        url = f"https://youtube.com/watch?v={results[0]['id']}"
    
    # Get song info
    song = await get_youtube_stream_url(url)
    if not song:
        await processing_msg.edit_text("❌ Could not get song information!")
        return
    
    # Check if user is admin/creator
    try:
        member = await message.chat.get_member(message.from_user.id)
        if member.status not in ["creator", "administrator"]:
            await processing_msg.edit_text("❌ You need to be admin to play music!")
            return
    except:
        pass
    
    # Check if something is playing
    if chat_id in now_playing:
        # Add to queue
        queue = get_queue(chat_id)
        if len(queue) >= MAX_QUEUE_SIZE:
            await processing_msg.edit_text(f"❌ Queue is full! Max {MAX_QUEUE_SIZE} songs.")
            return
        
        queue.append(song)
        await processing_msg.edit_text(f"✅ Added to queue: **{song['title']}**\nPosition: #{len(queue)}")
    else:
        # Play immediately
        await processing_msg.edit_text("🎵 Playing...")
        await play_song(chat_id, song)

@bot.on_message(filters.command("splay") & filters.group)
async def search_play_command(client: Client, message: Message):
    """Search and play"""
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide a search query!\nExample: `/splay pop music`")
        return
    
    query = " ".join(message.command[1:])
    
    search_msg = await message.reply_text(f"🔍 Searching for: `{query}`")
    
    results = await search_youtube(query, limit=5)
    
    if not results:
        await search_msg.edit_text("❌ No results found!")
        return
    
    # Create inline keyboard with results
    buttons = []
    for i, result in enumerate(results):
        title = result['title'][:40] + "..." if len(result['title']) > 40 else result['title']
        duration = result.get('duration', 'N/A')
        buttons.append([
            InlineKeyboardButton(
                f"{i+1}. {title} ({duration})",
                callback_data=f"play_{result['id']}"
            )
        ])
    
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")])
    
    await search_msg.edit_text(
        "🔍 **Search Results:**\nChoose a song to play:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@bot.on_message(filters.command("queue") & filters.group)
async def queue_command(client: Client, message: Message):
    """Show queue"""
    chat_id = message.chat.id
    queue = get_queue(chat_id)
    
    if not queue and chat_id not in now_playing:
        await message.reply_text("🎶 Queue is empty!")
        return
    
    queue_text = "📋 **Current Queue:**\n\n"
    
    if chat_id in now_playing:
        current = now_playing[chat_id]
        duration = format_duration(current.get('duration', 0))
        queue_text += f"🎵 **Now Playing:** {current['title']} ({duration})\n\n"
    
    if queue:
        queue_text += "**Up Next:**\n"
        for i, song in enumerate(queue, 1):
            duration = format_duration(song.get('duration', 0))
            queue_text += f"{i}. {song['title']} ({duration})\n"
        
        if len(queue) > 10:
            queue_text += f"\n... and {len(queue) - 10} more songs"
        
        queue_text += f"\n**Total:** {len(queue)} songs"
    else:
        queue_text += "No songs in queue"
    
    await message.reply_text(queue_text)

@bot.on_message(filters.command(["pause", "resume", "skip", "stop"]))
async def control_commands(client: Client, message: Message):
    """Handle control commands"""
    chat_id = message.chat.id
    command = message.command[0]
    
    try:
        if command == "pause":
            await call.pause_stream(chat_id)
            await message.reply_text("⏸ Playback paused")
        
        elif command == "resume":
            await call.resume_stream(chat_id)
            await message.reply_text("▶️ Playback resumed")
        
        elif command == "skip":
            if chat_id in now_playing:
                await message.reply_text("⏭ Skipping...")
                await play_next(chat_id)
            else:
                await message.reply_text("❌ Nothing is playing!")
        
        elif command == "stop":
            await call.leave_group_call(chat_id)
            if chat_id in queues:
                queues[chat_id].clear()
            now_playing.pop(chat_id, None)
            loop_mode.pop(chat_id, None)
            await message.reply_text("🛑 Playback stopped and queue cleared")
    
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")

@bot.on_message(filters.command("loop"))
async def loop_command(client: Client, message: Message):
    """Toggle loop mode"""
    chat_id = message.chat.id
    loop_mode[chat_id] = not loop_mode.get(chat_id, False)
    status = "ON" if loop_mode[chat_id] else "OFF"
    await message.reply_text(f"🔁 Loop mode: **{status}**")

@bot.on_message(filters.command("volume"))
async def volume_command(client: Client, message: Message):
    """Set volume"""
    if len(message.command) != 2:
        await message.reply_text("❌ Usage: `/volume 1-200`\nExample: `/volume 80`")
        return
    
    try:
        volume = int(message.command[1])
        if 1 <= volume <= 200:
            chat_id = message.chat.id
            user_volumes[chat_id] = volume
            
            try:
                await call.set_my_volume(chat_id, volume)
                await message.reply_text(f"🔊 Volume set to {volume}%")
            except:
                await message.reply_text(f"🔊 Volume will be set to {volume}% on next song")
        else:
            await message.reply_text("❌ Volume must be between 1 and 200")
    except ValueError:
        await message.reply_text("❌ Please enter a valid number!")

@bot.on_message(filters.command("clear"))
async def clear_command(client: Client, message: Message):
    """Clear queue"""
    chat_id = message.chat.id
    queue = get_queue(chat_id)
    
    if queue:
        queue.clear()
        await message.reply_text("🗑 Queue cleared!")
    else:
        await message.reply_text("❌ Queue is already empty!")

@bot.on_message(filters.command("nowplaying") | filters.command("np"))
async def nowplaying_command(client: Client, message: Message):
    """Show now playing"""
    chat_id = message.chat.id
    
    if chat_id not in now_playing:
        await message.reply_text("❌ Nothing is playing!")
        return
    
    song = now_playing[chat_id]
    duration = format_duration(song.get('duration', 0))
    
    text = f"""
🎵 **Now Playing:** {song['title']}
⏰ **Duration:** {duration}
👤 **Channel:** {song.get('channel', 'Unknown')}
🔗 [Watch on YouTube]({song.get('youtube_url', '')})
    """
    
    await message.reply_text(text)

@bot.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    """Show help"""
    help_text = f"""
**🎵 Music Bot Help**

**Basic Commands:**
/play [song/URL] - Play a song
/splay [query] - Search and play
/queue - Show queue
/pause - Pause playback
/resume - Resume playback
/skip - Skip current song
/stop - Stop everything
/loop - Toggle loop
/volume [1-200] - Set volume
/clear - Clear queue
/nowplaying - Current song

**Queue Management:**
• Songs are added to queue when something is playing
• Max {MAX_QUEUE_SIZE} songs in queue
• Use /queue to see all songs

**Tips:**
1. Start voice chat first
2. Give me admin rights
3. Use /play to start
4. Use inline buttons for quick control
    """
    
    await message.reply_text(help_text)

# ========== CALLBACK HANDLERS ==========
@bot.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    """Handle inline button clicks"""
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
                await callback_query.answer("❌ Nothing is playing!")
        
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
        
        elif data == "show_queue":
            await queue_command(client, callback_query.message)
            await callback_query.answer()
        
        elif data.startswith("play_"):
            video_id = data.split("_")[1]
            url = f"https://youtube.com/watch?v={video_id}"
            
            await callback_query.answer("🎵 Loading...")
            
            # Get song info
            song = await get_youtube_stream_url(url)
            if not song:
                await callback_query.answer("❌ Error loading song!")
                return
            
            # Check if playing
            if chat_id in now_playing:
                queue = get_queue(chat_id)
                queue.append(song)
                await callback_query.message.edit_text(
                    f"✅ Added to queue: **{song['title']}**"
                )
            else:
                await callback_query.message.delete()
                await play_song(chat_id, song)
        
        elif data == "cancel_search":
            await callback_query.message.delete()
            awai
