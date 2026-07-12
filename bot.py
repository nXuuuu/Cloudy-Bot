import os
import re
import asyncio
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN") 
URL_REGEX = r"(https?://(?:www\.)?(?:tiktok\.com|vt\.tiktok\.com|facebook\.com|fb\.watch|fb\.com/reel)[^\s]+)"
DOWNLOAD_DIR = "downloads"

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
    await update.message.reply_text("👋 Hello! Send a TikTok or Facebook link into the group, and I'll download it!")

def download_media(url):
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
        
    file_path_template = f"{DOWNLOAD_DIR}/%(id)s.%(ext)s"
    
    ydl_opts = {
        'outtmpl': file_path_template,
        # Caps resolution at 720p and prioritizes smaller sizes to protect your Render bandwidth caps
        'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best',
        'format_sort': ['res:720', '+size'], 
        'max_filesize': 49 * 1024 * 1024, # Hard fallback at 49MB for Telegram restrictions
        'quiet': True,
        'no_warnings': True,
    }

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
        
    url = urls[0]
    status_msg = await update.message.reply_text("⏳ Processing link...", reply_to_message_id=update.message.message_id)
    
    loop = asyncio.get_event_loop()
    file_path = await loop.run_in_executor(None, download_media, url)
    
    if file_path and os.path.exists(file_path):
        try:
            await status_msg.edit_text("📤 Uploading media...")
            with open(file_path, 'rb') as media_file:
                if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    await update.message.reply_photo(photo=media_file, reply_to_message_id=update.message.message_id)
                else:
                    await update.message.reply_video(video=media_file, reply_to_message_id=update.message.message_id, supports_streaming=True)
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(f"❌ Upload Failed. (Error: {str(e)})")
        finally:
            os.remove(file_path)
    else:
        await status_msg.edit_text("❌ Download Failed. The file might be over 50MB or private.")

def main():
    if not BOT_TOKEN:
        print("CRITICAL: BOT_TOKEN environment variable is missing!")
        return
        
    keep_alive() # Fires up the background Flask server
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Bot is actively polling...")
    app.run_polling()

if __name__ == "__main__":
    main()