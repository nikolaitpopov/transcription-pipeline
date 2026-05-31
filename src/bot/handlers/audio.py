"""Audio message handler for the Telegram bot."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

from src.config import (
    ALLOWED_AUDIO_FORMATS,
    AUDIO_INBOX_DIR,
    MAX_FILE_SIZE_BYTES,
    MAX_FILE_SIZE_MB,
    ALLOWED_CHAT_ID
)
from src.bot.db import create_job

logger = logging.getLogger(__name__)

# Create router for audio handlers
router = Router()


def check_chat_access(chat_id: int) -> bool:
    """Check if the chat is allowed to use the bot."""
    if ALLOWED_CHAT_ID is None:
        return True  # No restriction if not configured
    return chat_id == ALLOWED_CHAT_ID


def get_file_extension(filename: str) -> str:
    """Extract file extension from filename."""
    if not filename:
        return ""
    ext = Path(filename).suffix.lstrip(".").lower()
    return ext


def is_audio_format_allowed(extension: str) -> bool:
    """Check if the file extension is in the allowed list."""
    return extension in ALLOWED_AUDIO_FORMATS


def format_file_size(size_bytes: int) -> str:
    """Format file size in MB with 2 decimal places."""
    size_mb = size_bytes / (1024 * 1024)
    return f"{size_mb:.2f}"


async def save_audio_file(message: Message, file_id: str, extension: str) -> Path:
    """
    Download and save audio file from Telegram.
    
    Args:
        message: Telegram message object
        file_id: Telegram file ID
        extension: File extension
        
    Returns:
        Path to saved file
    """
    # Create inbox directory if it doesn't exist
    AUDIO_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    
    # Generate filename with timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{file_id}.{extension}"
    file_path = AUDIO_INBOX_DIR / filename
    
    # Download file from Telegram
    file = await message.bot.get_file(file_id)
    await message.bot.download_file(file.file_path, file_path)
    
    logger.info(f"Saved audio file: {file_path}")
    return file_path


async def process_audio_message(message: Message, file_id: str, file_size: int, original_filename: str):
    """
    Process audio message: validate, save, and create job.
    
    Args:
        message: Telegram message object
        file_id: Telegram file ID
        file_size: File size in bytes
        original_filename: Original filename
    """
    # Check chat access
    if not check_chat_access(message.chat.id):
        await message.answer("❌ У вас нет доступа к этому боту.")
        return
    
    # Check file size
    if file_size > MAX_FILE_SIZE_BYTES:
        size_mb = format_file_size(file_size)
        await message.answer(
            f"❌ Файл слишком большой ({size_mb} МБ).\n"
            f"Максимальный размер: {MAX_FILE_SIZE_MB} МБ."
        )
        return
    
    # Get file extension
    extension = get_file_extension(original_filename)
    
    # Check if format is allowed
    if not is_audio_format_allowed(extension):
        await message.answer(
            f"❌ Неподдерживаемый формат файла: .{extension}\n"
            f"Допустимые форматы: {', '.join(ALLOWED_AUDIO_FORMATS)}"
        )
        return
    
    try:
        # Save file
        file_path = await save_audio_file(message, file_id, extension)
        
        # Create job in database
        job_id = await create_job(
            file_path=str(file_path.absolute()),
            original_filename=original_filename,
            telegram_chat_id=message.chat.id
        )
        
        # Send success message
        size_mb = format_file_size(file_size)
        await message.answer(
            f"✅ Файл получен и поставлен в очередь.\n"
            f"ID задания: #{job_id}\n"
            f"Формат: {extension} · Размер: {size_mb} МБ\n"
            f"Ожидайте результат — это займёт несколько минут."
        )
        
        logger.info(f"Created job #{job_id} for chat {message.chat.id}")
        
    except Exception as e:
        logger.error(f"Error processing audio message: {e}", exc_info=True)
        await message.answer(
            "❌ Произошла ошибка при обработке файла. Попробуйте ещё раз."
        )


@router.message(F.voice)
async def handle_voice(message: Message):
    """Handle voice messages."""
    voice = message.voice
    # Voice messages are typically in .ogg format
    await process_audio_message(
        message=message,
        file_id=voice.file_id,
        file_size=voice.file_size,
        original_filename=f"voice_{voice.file_unique_id}.ogg"
    )


@router.message(F.audio)
async def handle_audio(message: Message):
    """Handle audio files."""
    audio = message.audio
    filename = audio.file_name or f"audio_{audio.file_unique_id}.mp3"
    await process_audio_message(
        message=message,
        file_id=audio.file_id,
        file_size=audio.file_size,
        original_filename=filename
    )


@router.message(F.document)
async def handle_document(message: Message):
    """Handle documents (check if it's an audio file)."""
    document = message.document
    filename = document.file_name or f"document_{document.file_unique_id}"
    
    # Check if it's an audio file by extension
    extension = get_file_extension(filename)
    if not is_audio_format_allowed(extension):
        # Not an audio file, ignore silently or inform user
        await message.answer(
            "ℹ️ Пожалуйста, отправьте аудиофайл в одном из поддерживаемых форматов:\n"
            f"{', '.join(ALLOWED_AUDIO_FORMATS)}"
        )
        return
    
    await process_audio_message(
        message=message,
        file_id=document.file_id,
        file_size=document.file_size,
        original_filename=filename
    )


@router.message(Command("start"))
async def handle_start(message: Message):
    """Handle /start command."""
    await message.answer(
        "👋 Привет! Я бот для транскрибации аудио.\n\n"
        "Отправьте мне:\n"
        "• Голосовое сообщение\n"
        "• Аудиофайл\n"
        "• Документ с аудио\n\n"
        f"Поддерживаемые форматы: {', '.join(ALLOWED_AUDIO_FORMATS)}\n"
        f"Максимальный размер: {MAX_FILE_SIZE_MB} МБ"
    )


@router.message(Command("help"))
async def handle_help(message: Message):
    """Handle /help command."""
    await message.answer(
        "📖 Инструкция:\n\n"
        "1. Отправьте аудиофайл боту\n"
        "2. Получите ID задания\n"
        "3. Дождитесь результата транскрибации\n\n"
        f"Поддерживаемые форматы: {', '.join(ALLOWED_AUDIO_FORMATS)}\n"
        f"Максимальный размер файла: {MAX_FILE_SIZE_MB} МБ"
    )
