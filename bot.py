import os
import re
import asyncio
import subprocess
import sys
import time
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
import yt_dlp

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
URL_REGEX = r"(https?://(?:www\.)?(?:tiktok\.com|vt\.tiktok\.com|facebook\.com|fb\.watch|fb\.com)[^\s]+)"
DOWNLOAD_DIR = "downloads"

# 🛡️ ANTI-SPAM TRACKER
user_cooldowns = {}
COOLDOWN_DURATION = 60 

# --- FLASK WEB SERVER (FOR THE PING TRICK) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_server)
    t.daemon = True
    t.start()

# --- TELEGRAM BOT LOGIC ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 ជំរាបសួរថ្ងៃនេះសុំ Full TP! សូមផ្ញើលីង TikTok ឬ Facebook Reel មកទីនេះខ្ញុំនឹងទាញយកវាជូន។")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "ℹ️ <b>How to use CloudyBot:</b>\n\n"
        "1. Add me to your group chat.\n"
        "2. Make sure I have permission to read/send messages.\n"
        "3. Simply paste a link from <b>TikTok</b> or <b>Facebook (Reels/Videos)</b>.\n\n"
        "⚠️ <i>Note: Files larger than 50MB cannot be sent due to Telegram limits.</i>"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    about_text = (
        "⚡️ <b>CloudyBot v1.0</b> ⚡️\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🚀 <b>Purpose:</b> Video conversions bot.\n\n"
        "👤 <b>Creator:</b> @sokunthanou\n"
        "👥 <b>Team:</b> <a href='https://www.finhubkh.com/en'><b>FINHUBKH</b></a>\n"
        "🌐 <b>Education Portal:</b> https://www.finhubkh.com/en\n\n"
        "💡 <i>Type /help to see how to auto-extract TikTok & Facebook media instantly.</i>\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(about_text, parse_mode="HTML", disable_web_page_preview=False)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 <b>Status:</b> Online & operational on the cloud!", parse_mode="HTML")


# --- VIDEO/IMAGE DOWNLOAD PARSER ENGINE ---
def download_media(url):
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
        
    file_path_template = f"{DOWNLOAD_DIR}/%(id)s.%(ext)s"
    
    ydl_opts = {
        'outtmpl': file_path_template,
        'format': (
            'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/'
            'best[height<=720][ext=mp4]/'
            'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/'
            'best[height<=480][ext=mp4]/'
            'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/'
            'best[height<=360][ext=mp4]/'
            'worst[ext=mp4]/worst'
        ),
        'format_sort': ['res:720', '+size'], 
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        
        # 🌐 Optimized headers that pass proxy credentials cleanly without 407 errors
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Sec-Fetch-Mode': 'navigate',
        }
    }

    # 🌐 PROXY CONFIGURATION: Loaded automatically from your Render Env
    PROXY_URL = os.getenv("PROXY_URL")
    if PROXY_URL:
        ydl_opts['proxy'] = PROXY_URL
        ydl_opts['proxy_username'] = 'owxgqdqt'
        ydl_opts['proxy_password'] = 'bl25td2gpu4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info_dict)
            
            if not os.path.exists(file_path):
                base_path = os.path.splitext(file_path)[0]
                for ext in ['.mp4', '.mkv', '.webm', '.jpg', '.png']:
                    if os.path.exists(base_path + ext):
                        return base_path + ext
            return file_path
    except Exception as e:
        print(f"Download error: {e}")
        return None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    if not message_text:
        return
        
    urls = re.findall(URL_REGEX, message_text)
    if not urls:
        return
        
    # 🛡️ CHECK COOLDOWN BEFORE PROCESSING ANYTHING
    user_id = update.message.from_user.id
    current_time = time.time()
    
    if user_id in user_cooldowns:
        time_passed = current_time - user_cooldowns[user_id]
        if time_passed < COOLDOWN_DURATION:
            remaining_time = int(COOLDOWN_DURATION - time_passed)
            cooldown_msg = await update.message.reply_text(
                f"⏳ <b>សុំ Cooldown មួយ! Auto Deleting in 10 Seconds.</b>\n"
                f"Please wait <b>{remaining_time}s</b> before sending another link to prevent spam.",
                reply_to_message_id=update.message.message_id,
                parse_mode="HTML"
            )
            # 🧹 1. Clear cooldown warning notice after 10 seconds
            await asyncio.sleep(10)
            try:
                await cooldown_msg.delete()
            except Exception:
                pass
            return

    # Update the timestamp immediately
    user_cooldowns[user_id] = current_time
    
    url = urls[0]
    status_msg = await update.message.reply_text("⏳ Processing link...", reply_to_message_id=update.message.message_id)
    
    loop = asyncio.get_event_loop()
    file_path = await loop.run_in_executor(None, download_media, url)
    
    if file_path and os.path.exists(file_path):
        try:
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if file_size_mb >= 50.0:
                await status_msg.edit_text(
                    f"⚠️ <b>Video too large!</b>\n\n"
                    f"Even at a reduced quality, this media is <b>{file_size_mb:.1f}MB</b>, which exceeds Telegram's strict 50MB limit for standard bots. Auto Deleting in 10 Seconds.",
                    parse_mode="HTML"
                )
                os.remove(file_path) 
                
                # 🧹 2. Clear large file warning after 10 seconds
                await asyncio.sleep(10)
                try:
                    await status_msg.delete()
                except Exception:
                    pass
                return

            await status_msg.edit_text("📤 Uploading media...")
            with open(file_path, 'rb') as media_file:
                if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    await update.message.reply_photo(
                        photo=media_file, 
                        reply_to_message_id=update.message.message_id,
                        connect_timeout=300, read_timeout=300, write_timeout=300
                    )
                else:
                    await update.message.reply_video(
                        video=media_file, 
                        reply_to_message_id=update.message.message_id, 
                        supports_streaming=True,
                        connect_timeout=300, read_timeout=300, write_timeout=300
                    )
            # ✅ SUCCESS: Delete processing alert cleanly
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(f"❌ Upload Failed. (Error: {str(e)}) Auto Deleting in 10 Seconds.")
            if os.path.exists(file_path):
                os.remove(file_path)
            
            # 🧹 3. Clear failed upload notice after 10 seconds
            await asyncio.sleep(10)
            try:
                await status_msg.delete()
            except Exception:
                pass
    else:
        await status_msg.edit_text("❌ Download Failed. The file might be private or temporarily unreachable. Auto Deleting in 10 Seconds.")
        
        # 🧹 4. Clear failed download alert after 10 seconds
        await asyncio.sleep(10)
        try:
            await status_msg.delete()
        except Exception:
            pass

def main():
    if not BOT_TOKEN:
        print("CRITICAL: BOT_TOKEN environment variable is missing!")
        return
        
    print("🔄 Checking for engine updates...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"])
        print("✅ Engine is up-to-date!")
    except Exception as update_error:
        print(f"⚠️ Automatic update check skipped: {update_error}")

    keep_alive() 
    
    request_config = HTTPXRequest(connect_timeout=300, read_timeout=300, write_timeout=300)
    app = Application.builder().token(BOT_TOKEN).request(request_config).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("status", status_command))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Bot is actively polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
