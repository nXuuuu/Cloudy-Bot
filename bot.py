import os
import re
import asyncio
import subprocess
import sys
import time
from threading import Thread
from flask import Flask
from telegram import Update, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
import httpx
import yt_dlp

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
URL_REGEX = r"(https?://(?:www\.)?(?:tiktok\.com|vt\.tiktok\.com|facebook\.com|fb\.watch|fb\.com)[^\s]+)"
DOWNLOAD_DIR = "downloads"

# 🛡️ ANTI-SPAM MULTI-POST TRACKER
user_cooldowns = {}       
COOLDOWN_DURATION = 60    
MAX_POSTS_ALLOWED = 3     

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
    
    # 📱 UPDATED HEADERS TO MIMIC IPHONE APP
    headers = {
        'User-Agent': 'com.zhiliaoapp.musically/2024040010 (iPhone; iOS 17.4; Scale/3.00)',
        'Referer': 'https://www.tiktok.com/',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    
    ydl_opts = {
        'outtmpl': file_path_template,
        'format': (
            'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/'
            'best[height<=720][ext=mp4]/'
            'worst[ext=mp4]/worst'
        ),
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'ffmpeg_location': '.venv/bin/',
        'http_headers': headers,
    }

    PROXY_URL = os.getenv("PROXY_URL")
    httpx_proxy = None
    if PROXY_URL:
        clean_proxy = PROXY_URL.strip().rstrip('/')
        ydl_opts['proxy'] = clean_proxy
        ydl_opts['proxy_username'] = 'owxgqdqt'
        ydl_opts['proxy_password'] = 'bl25td2gpu4'
        raw_ip_port = clean_proxy.replace('http://', '').replace('https://', '')
        httpx_proxy = f"http://owxgqdqt:bl25td2gpu4@{raw_ip_port}"

    # 🎭 PRE-SWAPPER
    if "/photo/" in url:
        url = url.replace("/photo/", "/video/")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info_dict = ydl.extract_info(url, download=False)
            except Exception as e:
                # Catch-and-Retry trap
                error_msg = str(e)
                if "Unsupported URL" in error_msg and "/photo/" in error_msg:
                    match = re.search(r'(https?://[^\s\'">]+)', error_msg)
                    if match:
                        true_url = match.group(1).replace("/photo/", "/video/")
                        info_dict = ydl.extract_info(true_url, download=False)
                    else:
                        raise e
                else:
                    raise e
            
            # 📸 CAROUSEL DETECTOR
            if info_dict.get('images'):
                images = info_dict.get('images', [])
                downloaded_photo_paths = []
                post_id = info_dict.get('id', str(int(time.time())))
                
                try:
                    with httpx.Client(proxy=httpx_proxy, timeout=30.0, verify=False) as client:
                        for index, img_entry in enumerate(images[:10]):
                            img_url = img_entry.get('url')
                            if img_url:
                                photo_path = f"{DOWNLOAD_DIR}/{post_id}_{index}.jpg"
                                response = client.get(img_url, headers=headers)
                                response.raise_for_status()
                                with open(photo_path, 'wb') as out_file:
                                    out_file.write(response.content)
                                downloaded_photo_paths.append(photo_path)
                        return downloaded_photo_paths
                except Exception as img_e:
                    print(f"Image download error: {img_e}")
                    return None

            # 📹 VIDEO DOWNLOAD
            info_dict = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info_dict)
            return file_path
    except Exception as e:
        print(f"Download error: {e}")
        return None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    if not message_text: return
    urls = re.findall(URL_REGEX, message_text)
    if not urls: return
    
    # 🛡️ COOLDOWN
    user_id = update.message.from_user.id
    current_time = time.time()
    if user_id not in user_cooldowns:
        user_cooldowns[user_id] = {"count": 0, "reset_time": current_time + COOLDOWN_DURATION}
    user_data = user_cooldowns[user_id]
    if current_time > user_data["reset_time"]:
        user_data["count"] = 0
        user_data["reset_time"] = current_time + COOLDOWN_DURATION
    if user_data["count"] >= MAX_POSTS_ALLOWED:
        return
    user_data["count"] += 1
    url = urls[0]
        
    status_msg = await update.message.reply_text("⏳ Processing...", reply_to_message_id=update.message.message_id)
    
    loop = asyncio.get_event_loop()
    download_result = await loop.run_in_executor(None, download_media, url)
    
    if download_result:
        try:
            if isinstance(download_result, list):
                await status_msg.edit_text("📤 Uploading carousel...")
                media_group = [InputMediaPhoto(open(p, 'rb')) for p in download_result]
                await update.message.reply_media_group(media=media_group, reply_to_message_id=update.message.message_id)
                for p in download_result: os.remove(p)
            else:
                with open(download_result, 'rb') as f:
                    await update.message.reply_video(video=f, reply_to_message_id=update.message.message_id)
                os.remove(download_result)
            await status_msg.delete()
        except:
            await status_msg.edit_text("❌ Upload failed.")
    else:
        await status_msg.edit_text("❌ Error downloading.")

def main():
    if not BOT_TOKEN: return
    keep_alive() 
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
