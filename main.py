import os
import logging
import tempfile
import requests
from fastapi import FastAPI
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from dotenv import load_dotenv

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

# Initialize Telegram client
telegram_client = Client(
    "dailymotion_uploader",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
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
            response = requests.post(auth_url, data=payload)
            response.raise_for_status()
            self.access_token = response.json().get("access_token")
            logger.info("Dailymotion authentication successful")
            return True
        except Exception as e:
            logger.error(f"Dailymotion auth failed: {e}")
            return False
            
    async def upload_video(self, file_path, title="Uploaded from Telegram"):
        try:
            if not self.access_token:
                if not await self.authenticate():
                    return None
                    
            # Step 1: Create video entry
            create_url = f"{self.base_url}/me/videos"
            headers = {"Authorization": f"Bearer {self.access_token}"}
            params = {
                "title": title,
                "published": True,
                "channel": "videogames"
            }
            create_response = requests.post(create_url, headers=headers, data=params)
            create_response.raise_for_status()
            video_data = create_response.json()
            video_id = video_data.get("id")
            upload_url = video_data.get("url")
            
            # Step 2: Upload the file
            with open(file_path, "rb") as video_file:
                upload_response = requests.put(upload_url, data=video_file)
                upload_response.raise_for_status()
                
            return f"https://www.dailymotion.com/video/{video_id}"
        except Exception as e:
            logger.error(f"Upload failed: {e}")
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

        # Download file
        await client.download_media(message, file_name=temp_path)
        file_size = os.path.getsize(temp_path) / (1024 * 1024)
        logger.info(f"Downloaded file: {temp_path} ({file_size:.2f} MB)")

        # Start upload
        await status_msg.edit_text("📤 Uploading to Dailymotion...")
        
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
            await status_msg.edit_text("❌ Failed to upload video")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await message.reply(f"❌ Error: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)

@telegram_client.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply("""
🤖 **Dailymotion Video Uploader Bot**

🔹 Send me any video file (MP4, MKV, etc.)
🔹 I'll upload it to Dailymotion automatically
🔹 Supports large files (up to 2GB)

📌 Just send me a video now!
""")

async def run():
    await telegram_client.start()
    logger.info("Bot started")
    await idle()

if __name__ == "__main__":
    import uvicorn
    import asyncio
    from threading import Thread

    # Start FastAPI server
    def run_server():
        uvicorn.run(app, host="0.0.0.0", port=8080)
    
    Thread(target=run_server, daemon=True).start()
    
    # Run Telegram client
    asyncio.get_event_loop().run_until_complete(run())
