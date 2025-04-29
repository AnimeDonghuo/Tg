import os
import logging
import tempfile
from fastapi import FastAPI
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from dailymotion import Dailymotion
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI for health checks
app = FastAPI()

@app.get("/")
async def health_check():
    return {"status": "OK", "service": "Telegram to Dailymotion Uploader"}

# Required configuration
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Dailymotion configuration
DM_API_KEY = os.getenv("DAILYMOTION_API_KEY")
DM_API_SECRET = os.getenv("DAILYMOTION_API_SECRET")
DM_USERNAME = os.getenv("DAILYMOTION_USERNAME")
DM_PASSWORD = os.getenv("DAILYMOTION_PASSWORD")

# Initialize Pyrogram client
telegram_client = Client(
    "dailymotion_uploader_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4
)

# Initialize Dailymotion client
dm = Dailymotion()

async def authenticate_dailymotion():
    try:
        dm.set_grant_type(
            "password",
            api_key=DM_API_KEY,
            api_secret=DM_API_SECRET,
            scope=["manage_videos"],
            info={"username": DM_USERNAME, "password": DM_PASSWORD}
        )
        logger.info("Dailymotion authentication successful")
        return True
    except Exception as e:
        logger.error(f"Dailymotion authentication failed: {e}")
        return False

@telegram_client.on_message(filters.video | filters.document)
async def handle_media(client: Client, message: Message):
    temp_path = None
    try:
        # Check file type
        if message.document and not message.document.mime_type.startswith("video/"):
            await message.reply("❌ Please send a video file (MP4, MKV, AVI, etc.)")
            return

        # Start download
        status_msg = await message.reply("📥 Downloading your video...")

        # Create temp file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
            temp_path = temp_file.name

        # Download file
        await client.download_media(message, file_name=temp_path)
        file_size = os.path.getsize(temp_path) / (1024 * 1024)  # in MB
        logger.info(f"Downloaded file: {temp_path} ({file_size:.2f} MB)")

        # Authenticate with Dailymotion
        if not await authenticate_dailymotion():
            await status_msg.edit_text("❌ Failed to authenticate with Dailymotion")
            return

        # Start upload
        await status_msg.edit_text("📤 Uploading to Dailymotion (this may take a while)...")
        
        # Upload to Dailymotion
        url = dm.upload(temp_path)
        result = dm.post(
            "/me/videos",
            {
                "url": url,
                "title": message.caption or f"Uploaded from Telegram by {message.from_user.first_name}",
                "published": True,
                "channel": "videogames",
                "tags": "telegram,upload"
            }
        )

        # Get video URL
        video_id = result.get("id")
        video_url = f"https://www.dailymotion.com/video/{video_id}"
        
        await status_msg.edit_text(
            f"✅ Upload Successful!\n\n"
            f"📹 Title: {result.get('title', 'No title')}\n"
            f"🔗 [View on Dailymotion]({video_url})\n\n"
            f"⏳ Video is processing and may take a few minutes to be available."
        )
        logger.info(f"Upload successful: {video_url}")

    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        error_msg = f"❌ Error: {str(e)}"
        if "Quota" in str(e):
            error_msg += "\n\n⚠️ Daily upload limit reached!"
        await message.reply(error_msg)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)

@telegram_client.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply("""
🤖 **Dailymotion Video Uploader Bot**

🔹 Send me any video file (MP4, MKV, AVI, etc.)
🔹 I'll upload it to Dailymotion automatically
🔹 Supports large files (up to 2GB)

📌 Just send me a video now!

⚠️ Note: 
- Videos may take time to process on Dailymotion
- Maximum file size: 2GB
- Supported formats: MP4, MKV, AVI, MOV, etc.
""")

async def run():
    await telegram_client.start()
    logger.info("Telegram bot started")
    await idle()

if __name__ == "__main__":
    import uvicorn
    import asyncio
    from threading import Thread

    # Start FastAPI server in a separate thread
    def run_fastapi():
        uvicorn.run(app, host="0.0.0.0", port=8080)

    Thread(target=run_fastapi, daemon=True).start()
    
    # Start Telegram client
    asyncio.get_event_loop().run_until_complete(run())
