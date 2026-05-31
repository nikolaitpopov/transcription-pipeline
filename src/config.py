"""Configuration module for the transcription pipeline bot."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram bot configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

ALLOWED_CHAT_ID = os.getenv("ALLOWED_CHAT_ID")
if ALLOWED_CHAT_ID:
    ALLOWED_CHAT_ID = int(ALLOWED_CHAT_ID)

# Data directory configuration
DATA_DIR = os.getenv("DATA_DIR")
if not DATA_DIR:
    # Default to ./data for local development
    DATA_DIR = "./data"

DATA_DIR = Path(DATA_DIR).resolve()

# Audio configuration
AUDIO_INBOX_DIR = DATA_DIR / "audio" / "inbox"
ALLOWED_AUDIO_FORMATS = ["mp3", "mp4", "m4a", "wav", "ogg", "webm", "flac"]
MAX_FILE_SIZE_MB = 200
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Database configuration
DB_PATH = DATA_DIR / "jobs.db"
