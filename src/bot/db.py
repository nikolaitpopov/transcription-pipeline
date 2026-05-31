"""Database module for managing jobs queue."""

import aiosqlite
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.config import DB_PATH


async def init_db():
    """Initialize the SQLite database and create tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                telegram_chat_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error_message TEXT
            )
        """)
        await db.commit()


async def create_job(
    file_path: str,
    original_filename: str,
    telegram_chat_id: int
) -> int:
    """
    Create a new job in the database.
    
    Args:
        file_path: Absolute path to the audio file
        original_filename: Original filename from Telegram
        telegram_chat_id: Telegram chat ID for sending results
        
    Returns:
        Job ID
    """
    now = datetime.now(timezone.utc).isoformat()
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO jobs (
                file_path,
                original_filename,
                telegram_chat_id,
                status,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, 'pending', ?, ?)
        """, (file_path, original_filename, telegram_chat_id, now, now))
        
        await db.commit()
        return cursor.lastrowid


async def update_job_status(
    job_id: int,
    status: str,
    error_message: Optional[str] = None
):
    """
    Update job status.
    
    Args:
        job_id: Job ID
        status: New status (pending/transcribing/transcribed/sending/done/error)
        error_message: Error message if status is 'error'
    """
    now = datetime.now(timezone.utc).isoformat()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE jobs
            SET status = ?,
                updated_at = ?,
                error_message = ?
            WHERE id = ?
        """, (status, now, error_message, job_id))
        
        await db.commit()


async def get_job(job_id: int) -> Optional[dict]:
    """
    Get job by ID.
    
    Args:
        job_id: Job ID
        
    Returns:
        Job dictionary or None if not found
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM jobs WHERE id = ?
        """, (job_id,))
        
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


async def get_pending_jobs(limit: int = 10) -> list[dict]:
    """
    Get pending jobs for processing.
    
    Args:
        limit: Maximum number of jobs to return
        
    Returns:
        List of job dictionaries
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM jobs
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT ?
        """, (limit,))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
