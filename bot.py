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

# --- FLASK ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot is alive!"
def run_server(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
def keep_alive(): Thread(target=run_server, daemon=True).start()

# --- HANDLERS ---
async def start(u, c): await u.message.reply_text("👋 Hello! Send a TikTok/FB link.")
async def status(u, c): await u.message.reply_text("🟢 Online")

# --- ENGINE ---
def download_media(url):
    if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)
    
    # Standard Desktop Headers to avoid fingerprinting
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'}
    
    ydl_opts = {
        'outtmpl': f"{DOWNLOAD_DIR}/%(id)s.%(ext)s",
        'format': 'best',
        'quiet': True,
        'http_headers': headers,
        'ffmpeg_location': '.venv/bin/'
    }

    PROXY_URL = os.getenv("PROXY_URL")
    if PROXY_URL:
        ydl_opts['proxy'] = PROXY_URL
        ydl_opts['proxy_username'] = 'owxgqdqt'
        ydl_opts['proxy_password'] = 'bl25td2gpu4'
        httpx_proxy = f"http://owxgqdqt:bl25td2gpu4@{PROXY_URL.replace('http://', '')}"
    else: httpx_proxy = None

    if "/photo/" in url: url = url.replace("/photo/", "/video/")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try: info = ydl.extract_info(url, download=False)
            except Exception as e:
                # Catch-and-Retry
                m = re.search(r'(https?://[^\s\'">]+)', str(e))
                if m: info = ydl.extract_info(m.group(1).replace("/photo/", "/video/"), download=False)
                else: raise e
            
            # Carousel Handling
            if info.get('images'):
                paths = []
                with httpx.Client(proxy=httpx_proxy, verify=False, headers=headers) as client:
                    for i, img in enumerate(info['images'][:10]):
                        p = f"{DOWNLOAD_DIR}/{info['id']}_{i}.jpg"
                        with open(p, 'wb') as f: f.write(client.get(img['url']).content)
                        paths.append(p)
                return paths
            
            # Video Handling
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    except: return None

async def handle_message(u, c):
    urls = re.findall(URL_REGEX, u.message.text or "")
    if not urls: return
    
    # Cooldown Logic
    uid = u.message.from_user.id
    if uid not in user_cooldowns: user_cooldowns[uid] = 0
    if user_cooldowns[uid] >= MAX_POSTS_ALLOWED: return
    user_cooldowns[uid] += 1
    
    status_msg = await u.message.reply_text("⏳ Processing...")
    res = await asyncio.get_event_loop().run_in_executor(None, download_media, urls[0])
    
    if res:
        try:
            if isinstance(res, list):
                await u.message.reply_media_group(media=[InputMediaPhoto(open(p, 'rb')) for p in res])
                for p in res: os.remove(p)
            else:
                with open(res, 'rb') as f: await u.message.reply_video(video=f)
                os.remove(res)
            await status_msg.delete()
        except: await status_msg.edit_text("❌ Upload failed.")
    else: await status_msg.edit_text("❌ Download failed.")

def main():
    keep_alive()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__": main()
