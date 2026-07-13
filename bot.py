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

# Track command replies to keep only the 2 most recent ones per chat
command_replies_tracker = {}

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

async def send_command_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode: str = None, disable_web_page_preview: bool = None):
    chat_id = update.effective_chat.id
    user_msg_id = update.message.message_id if update.message else None
    
    try:
        # Send the bot's reply
        bot_msg = await update.message.reply_text(
            text, 
            parse_mode=parse_mode, 
            disable_web_page_preview=disable_web_page_preview
        )
        bot_msg_id = bot_msg.message_id
    except Exception as e:
        print(f"Error sending command reply: {e}", flush=True)
        return

    # Initialize list for this chat if not present
    if chat_id not in command_replies_tracker:
        command_replies_tracker[chat_id] = []
        
    tracker = command_replies_tracker[chat_id]
    
    # Append the new pair
    tracker.append((bot_msg_id, user_msg_id))
    
    # If we have more than 2, delete the oldest
    while len(tracker) > 2:
        old_bot_id, old_user_id = tracker.pop(0)
        # Delete bot reply
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_bot_id)
        except Exception:
            pass
        # Delete user command
        if old_user_id:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=old_user_id)
            except Exception:
                pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_command_reply(
        update, 
        context, 
        "👋 ជំរាបសួរថ្ងៃនេះសុំ Full TP! សូមផ្ញើលីង TikTok ឬ Facebook Reel មកទីនេះខ្ញុំនឹងទាញយកវាជូន។"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "ℹ️ <b>How to use CloudyBot:</b>\n\n"
        "1. Add me to your group chat.\n"
        "2. Make sure I have permission to read/send messages.\n"
        "3. Simply paste a link from <b>TikTok</b> or <b>Facebook (Reels/Videos)</b>.\n\n"
        "⚠️ <i>Note: Files larger than 50MB cannot be sent due to Telegram limits.</i>"
    )
    await send_command_reply(update, context, help_text, parse_mode="HTML")

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
    await send_command_reply(update, context, about_text, parse_mode="HTML", disable_web_page_preview=False)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_command_reply(update, context, "🟢 <b>Status:</b> Online & operational on the cloud!", parse_mode="HTML")


# --- VIDEO/IMAGE DOWNLOAD PARSER ENGINE ---
def download_via_tikwm(url, download_dir, httpx_proxy=None, ydl_opts=None):
    api_url = "https://tikwm.com/api/"
    post_data = {
        "url": url,
        "hd": 1
    }
    
    # Try direct connection first, fallback to proxy if available and direct fails
    clients_to_try = [
        {"timeout": 30.0, "verify": False}  # Direct connection
    ]
    if httpx_proxy:
        clients_to_try.append({"timeout": 30.0, "verify": False, "proxy": httpx_proxy})  # Proxy connection
        
    for client_kwargs in clients_to_try:
        is_proxy_attempt = "proxy" in client_kwargs
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.post(api_url, data=post_data)
                response.raise_for_status()
                res_json = response.json()
                
                if res_json.get("code") != 0:
                    print(f"TikWM API Error: {res_json.get('msg')}", flush=True)
                    # If it's a specific API error (e.g. video not found), don't retry with proxy
                    return None
                    
                media_data = res_json.get("data", {})
                post_id = media_data.get("id", str(int(time.time())))
                
                # Check if it is a slideshow (photo mode)
                images = media_data.get("images")
                if images and isinstance(images, list):
                    downloaded_photo_paths = []
                    for index, img_entry in enumerate(images[:10]):  # Limit to 10 images
                        img_url = img_entry.get("url") if isinstance(img_entry, dict) else img_entry
                        if img_url:
                            photo_path = f"{download_dir}/{post_id}_{index}.jpg"
                            # Download each image
                            img_response = client.get(img_url, headers=ydl_opts.get('http_headers') if ydl_opts else None)
                            img_response.raise_for_status()
                            with open(photo_path, 'wb') as out_file:
                                out_file.write(img_response.content)
                            downloaded_photo_paths.append(photo_path)
                    print(f"Successfully downloaded slideshow carousel containing {len(downloaded_photo_paths)} images via TikWM API.", flush=True)
                    return downloaded_photo_paths
                
                # Otherwise, it's a video
                video_url = media_data.get("play") or media_data.get("hdplay")
                if video_url:
                    video_path = f"{download_dir}/{post_id}.mp4"
                    video_response = client.get(video_url)
                    video_response.raise_for_status()
                    with open(video_path, 'wb') as out_file:
                        out_file.write(video_response.content)
                    print(f"Successfully downloaded video to {video_path} via TikWM API.", flush=True)
                    return video_path
        except Exception as e:
            attempt_type = "with proxy" if is_proxy_attempt else "direct"
            print(f"TikWM download attempt failed ({attempt_type}): {e}", flush=True)
            # If direct failed and we have a proxy attempt left, we'll try it. Otherwise, loop ends.
            continue
            
    return None

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
        
        'ffmpeg_location': '.venv/bin/',
        
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Sec-Fetch-Mode': 'navigate',
        }
    }

    PROXY_URL = os.getenv("PROXY_URL")
    clean_proxy = None
    httpx_proxy = None
    
    if PROXY_URL:
        clean_proxy = PROXY_URL.strip().rstrip('/')
        ydl_opts['proxy'] = clean_proxy
        ydl_opts['proxy_username'] = 'owxgqdqt'
        ydl_opts['proxy_password'] = 'bl25td2gpu4'
        
        raw_ip_port = clean_proxy.replace('http://', '').replace('https://', '')
        httpx_proxy = f"http://owxgqdqt:bl25td2gpu4@{raw_ip_port}"

    original_url = url
    is_tiktok = "tiktok.com" in original_url or "vt.tiktok.com" in original_url

    # 🎭 PRE-SWAPPER: Catches explicit long photo URLs immediately
    if "/photo/" in url:
        url = url.replace("/photo/", "/video/")

    # Direct TikTok photo/slideshow bypass to TikWM
    if is_tiktok and "/photo/" in original_url:
        print("Tiktok photo/slideshow detected. Downloading via TikWM...", flush=True)
        tikwm_result = download_via_tikwm(original_url, DOWNLOAD_DIR, httpx_proxy, ydl_opts)
        if tikwm_result:
            print("Direct TikWM download successful.", flush=True)
            return tikwm_result

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            
            # --- 🚀 THE CATCH-AND-RETRY TRAP ---
            try:
                # Let yt-dlp attempt to unroll shortlinks naturally
                info_dict = ydl.extract_info(url, download=False)
            except Exception as e:
                error_msg = str(e)
                # If yt-dlp crashes because it found a hidden /photo/ URL...
                if "Unsupported URL" in error_msg and "/photo/" in error_msg:
                    # Scrape the unrolled URL directly out of the crash message
                    match = re.search(r'(https?://[^\s\'">]+)', error_msg)
                    if match:
                        true_url = match.group(1)
                        # Swap it safely and retry instantly
                        swapped_url = true_url.replace("/photo/", "/video/")
                        info_dict = ydl.extract_info(swapped_url, download=False)
                    else:
                        raise e
                else:
                    raise e
            
            # 📸 CAROUSEL DETECTOR
            if info_dict.get('formats') is None or len(info_dict.get('formats', [])) <= 1 or info_dict.get('images'):
                images = info_dict.get('images', [])
                if not images and info_dict.get('entries'):
                    images = info_dict['entries'][0].get('images', [])
                
                if images:
                    downloaded_photo_paths = []
                    post_id = info_dict.get('id', str(int(time.time())))
                    
                    # --- DOWNLOAD IMAGES USING HTTPX ---
                    try:
                        with httpx.Client(proxy=httpx_proxy, timeout=30.0, verify=False) as client:
                            for index, img_entry in enumerate(images[:10]):
                                img_url = img_entry.get('url')
                                if img_url:
                                    photo_path = f"{DOWNLOAD_DIR}/{post_id}_{index}.jpg"
                                    response = client.get(img_url, headers=ydl_opts['http_headers'])
                                    response.raise_for_status()
                                    with open(photo_path, 'wb') as out_file:
                                        out_file.write(response.content)
                                    downloaded_photo_paths.append(photo_path)
                            return downloaded_photo_paths
                    except Exception as img_e:
                        print(f"Image download error: {img_e}")
                        return None

            # 📹 STANDARD AUDIO-VIDEO MERGED DOWNLOAD
            info_dict = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info_dict)
            
            if not os.path.exists(file_path):
                base_path = os.path.splitext(file_path)[0]
                for ext in ['.mp4', '.mkv', '.webm', '.jpg', '.png']:
                    if os.path.exists(base_path + ext):
                        return base_path + ext
            return file_path
    except Exception as e:
        print(f"Download error: {e}", flush=True)
        if is_tiktok:
            print("Attempting TikWM fallback...", flush=True)
            tikwm_result = download_via_tikwm(original_url, DOWNLOAD_DIR, httpx_proxy, ydl_opts)
            if tikwm_result:
                print("TikWM fallback download successful.", flush=True)
                return tikwm_result
        return None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    message_text = update.message.text
        
    urls = re.findall(URL_REGEX, message_text)
    if not urls:
        return
        
    # 🛡️ DYNAMIC COUNTER COOLDOWN SYSTEM
    user_id = update.message.from_user.id
    current_time = time.time()
    
    if user_id not in user_cooldowns:
        user_cooldowns[user_id] = {"count": 0, "reset_time": current_time + COOLDOWN_DURATION}
        
    user_data = user_cooldowns[user_id]
    
    if current_time > user_data["reset_time"]:
        user_data["count"] = 0
        user_data["reset_time"] = current_time + COOLDOWN_DURATION

    if user_data["count"] >= MAX_POSTS_ALLOWED:
        remaining_time = int(user_data["reset_time"] - current_time)
        if remaining_time > 0:
            cooldown_msg = await update.message.reply_text(
                f"⏳ <b>សុំ Cooldown មួយ! Auto Deleting in 10 Seconds.</b>\n"
                f"You have reached the limit of <b>{MAX_POSTS_ALLOWED}</b> requests. Please wait <b>{remaining_time}s</b>.",
                reply_to_message_id=update.message.message_id,
                parse_mode="HTML"
            )
            await asyncio.sleep(10)
            try:
                await cooldown_msg.delete()
            except Exception:
                pass
            return

    user_data["count"] += 1
    url = urls[0]
        
    status_msg = await update.message.reply_text("⏳ Processing link...", reply_to_message_id=update.message.message_id)
    
    loop = asyncio.get_event_loop()
    download_result = await loop.run_in_executor(None, download_media, url)
    
    if download_result:
        try:
            # 🎨 TYPE DETECTOR: Handles image carousel lists
            if isinstance(download_result, list):
                await status_msg.edit_text("📤 Uploading photo album carousel...")
                
                media_group = []
                opened_files = []
                
                for path in download_result:
                    f = open(path, 'rb')
                    opened_files.append(f)
                    media_group.append(InputMediaPhoto(media=f))
                
                await update.message.reply_media_group(
                    media=media_group,
                    reply_to_message_id=update.message.message_id,
                    connect_timeout=300, read_timeout=300, write_timeout=300
                )
                
                for f in opened_files:
                    f.close()
                for path in download_result:
                    if os.path.exists(path):
                        os.remove(path)
                        
            # 📹 SINGLE FILE VIDEO HANDLING LOGIC
            else:
                file_path = download_result
                file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
                if file_size_mb >= 50.0:
                    await status_msg.edit_text(
                        f"⚠️ <b>Video too large!</b>\n\n"
                        f"Even at a reduced quality, this media is <b>{file_size_mb:.1f}MB</b>, which exceeds Telegram's strict 50MB limit for standard bots. Auto Deleting in 10 Seconds.",
                        parse_mode="HTML"
                    )
                    os.remove(file_path) 
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
                if os.path.exists(file_path):
                    os.remove(file_path)
                    
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(f"❌ Upload Failed. (Error: {str(e)}) Auto Deleting in 10 Seconds.")
            if isinstance(download_result, list):
                for path in download_result:
                    if os.path.exists(path): os.remove(path)
            elif os.path.exists(download_result):
                os.remove(download_result)
            await asyncio.sleep(10)
            try:
                await status_msg.delete()
            except Exception:
                pass
    else:
        await status_msg.edit_text("❌ Download Failed. The file might be private or temporarily unreachable. Auto Deleting in 10 Seconds.")
        await asyncio.sleep(10)
        try:
            await status_msg.delete()
        except Exception:
            pass

def main():
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    if not BOT_TOKEN:
        print("CRITICAL: BOT_TOKEN environment variable is missing!", flush=True)
        return
        
    print("🔄 Checking for engine updates...", flush=True)
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"])
        print("✅ Engine is up-to-date!", flush=True)
    except Exception as update_error:
        print(f"⚠️ Automatic update check skipped: {update_error}", flush=True)

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
