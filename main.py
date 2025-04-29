import os
import logging
import tempfile
import requests
import asyncio
from fastapi import FastAPI
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pyrogram.errors import RPCError
from dotenv import load_dotenv
from threading import Thread
import uvicorn

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI()

@app.get("/")
async def health_check():
    return {"status": "OK"}

# Configuration
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DM_API_KEY = os.getenv("DAILYMOTION_API_KEY")
DM_API_SECRET = os.getenv("DAILYMOTION_API_SECRET")
DM_USERNAME = os.getenv("DAILYMOTION_USERNAME")
DM_PASSWORD = os.getenv("DAILYMOTION_PASSWORD")

# Initialize Telegram client with optimized settings
telegram_client = Client(
    name="dailymotion_uploader",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4,
    sleep_threshold=60,
    no_updates=True
)

class DailymotionUploader:
    def __init__(self):
        self.access_token = None
        self.base_url = "https://api.dailymotion.com"
        
    async def authenticate(self):
        try:
            auth_url = f"{self.base_url}/oauth/token"
            payload = {
                "client_id": DM_API_KEY,
                "client_secret": DM_API_SECRET,
                "username": DM_USERNAME,
                "password": DM_PASSWORD,
                "grant_type": "password",
                "scope": "manage_videos"
            }
            response = requests.post(auth_url, data=payload, timeout=30)
            response.raise_for_status()
            self.access_token = response.json().get("access_token")
            logger.info("Dailymotion authentication successful")
            return True
        except Exception as e:
            logger.error(f"Dailymotion auth failed: {e}")
            return False
            
    async def upload_video(self, file_path, title="Uploaded from Telegram"):
        try:
            if not self.access_token and not await self.authenticate():
                return None
                
            # Step 1: Create video entry
            create_url = f"{self.base_url}/me/videos"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            params = {
                "title": title[:255],  # Truncate to max allowed length
                "published": "true",
                "channel": "videogames"
            }
            
            create_response = requests.post(
                create_url,
                headers=headers,
                data=params,
                timeout=30
            )
            create_response.raise_for_status()
            video_data = create_response.json()
            video_id = video_data.get("id")
            upload_url = video_data.get("url")
            
            if not upload_url:
                logger.error("No upload URL received")
                return None
                
            # Step 2: Upload the file
            with open(file_path, "rb") as video_file:
                upload_response = requests.put(
                    upload_url,
                    data=video_file,
                    timeout=300  # 5 minutes for large files
                )
                upload_response.raise_for_status()
                
            return f"https://www.dailymotion.com/video/{video_id}"
        except Exception as e:
            logger.error(f"Upload failed: {e}", exc_info=True)
            return None

dm_uploader = DailymotionUploader()

@telegram_client.on_message(filters.video | filters.document)
async def handle_media(client: Client, message: Message):
    temp_path = None
    try:
        # Check file type
        if message.document and not message.document.mime_type.startswith("video/"):
            await message.reply("❌ Please send a video file (MP4, MKV, etc.)")
            return

        # Start download
        status_msg = await message.reply("📥 Downloading your video...")

        # Create temp file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
            temp_path = temp_file.name

        # Download file with progress
        await client.download_media(
            message,
            file_name=temp_path,
            progress=lambda current, total: logger.info(f"Downloaded {current}/{total} bytes")
        )
        
        file_size = os.path.getsize(temp_path) / (1024 * 1024)
        logger.info(f"Downloaded file: {temp_path} ({file_size:.2f} MB)")

        # Start upload
        await status_msg.edit_text("📤 Uploading to Dailymotion (this may take several minutes for large files)...")
        
        # Upload to Dailymotion
        video_url = await dm_uploader.upload_video(
            temp_path,
            message.caption or f"Uploaded by {message.from_user.first_name}"
        )
        
        if video_url:
            await status_msg.edit_text(
                f"✅ Upload Successful!\n\n"
                f"🔗 [View on Dailymotion]({video_url})\n\n"
                f"⏳ Video may take a few minutes to process."
            )
        else:
            await status_msg.edit_text("❌ Failed to upload video. Please try again later.")

    except RPCError as e:
        logger.error(f"Telegram error: {e}", exc_info=True)
        await message.reply(f"❌ Telegram error: {str(e)}")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await message.reply(f"❌ Error: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass

@telegram_client.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply("""
🤖 **Dailymotion Video Uploader Bot**

🔹 Send me any video file (MP4, MKV, AVI, MOV, etc.)
🔹 I'll upload it to Dailymotion automatically
🔹 Supports large files (up to 2GB)

📌 Just send me a video now!

⚠️ Note: 
- Videos may take time to process on Dailymotion
- Maximum file size: 2GB
- Supported formats: MP4, MKV, AVI, MOV, etc.
""")

async def run_bot():
    await telegram_client.start()
    logger.info("Bot started successfully")
    await idle()

def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=8080)

if __name__ == "__main__":
    # Start FastAPI in a separate thread
    fastapi_thread = Thread(target=run_fastapi, daemon=True)
    fastapi_thread.start()
    
    # Run the bot in the main thread
    try:
        asyncio.get_event_loop().run_until_complete(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
