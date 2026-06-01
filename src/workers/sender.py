"""
Task 04 — MD generation and Telegram delivery worker.

Polls for jobs with status='diarized', generates a Markdown transcript file
and sends it to the user via Telegram bot as a document.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.types import BufferedInputFile

from src.config import DATA_DIR, DB_PATH, TELEGRAM_BOT_TOKEN

logger = logging.getLogger(__name__)

TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
RESULTS_DIR = DATA_DIR / "results"
POLL_INTERVAL = 5  # seconds


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_ts(seconds: float, total_duration: float = 0) -> str:
    """Format seconds as MM:SS or HH:MM:SS if duration > 1 hour."""
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if total_duration > 3600:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def _fmt_duration(seconds: float) -> str:
    """Format duration as MM:SS or HH:MM:SS."""
    return _fmt_ts(seconds, total_duration=seconds)


def _generate_md(data: dict, job_id: int, now: datetime) -> str:
    duration = data["duration_seconds"]
    speakers_count = data["speakers_count"]
    turns = data["turns"]

    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    duration_str = _fmt_duration(duration)

    lines = [
        "# Транскрипция звонка",
        "",
        f"**Дата:** {date_str}  ",
        f"**Время:** {time_str} UTC  ",
        f"**Длительность:** {duration_str}  ",
        f"**Спикеров:** {speakers_count}  ",
        f"**ID задания:** #{job_id}  ",
        "",
        "---",
        "",
        "## Диалог",
        "",
    ]

    for turn in turns:
        start = _fmt_ts(turn["start"], total_duration=duration)
        end = _fmt_ts(turn["end"], total_duration=duration)
        speaker = turn["speaker"]
        text = turn["text"].strip()

        lines.append(f"**{speaker}** · `{start} – {end}`")
        lines.append("")
        lines.append(text)
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _fetch_diarized_job() -> dict | None:
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM jobs WHERE status='diarized' ORDER BY created_at ASC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _set_status(job_id: int, status: str, error_message: str | None = None):
    import aiosqlite
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE jobs SET status=?, updated_at=?, error_message=? WHERE id=?",
            (status, now, error_message, job_id),
        )
        await db.commit()


# ── Worker loop ───────────────────────────────────────────────────────────────

async def run_worker():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logger.info("Sender worker started")

    try:
        while True:
            job = None
            try:
                job = await _fetch_diarized_job()
                if job is None:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                job_id = job["id"]
                chat_id = job["telegram_chat_id"]
                logger.info("Sending job %d to chat %d", job_id, chat_id)

                await _set_status(job_id, "sending")

                # Load diarized JSON
                diarized_path = TRANSCRIPTS_DIR / f"{job_id}_diarized.json"
                with open(diarized_path, encoding="utf-8") as f:
                    data = json.load(f)

                # Generate MD
                now = datetime.now(timezone.utc)
                md_content = _generate_md(data, job_id, now)

                date_tag = now.strftime("%Y%m%d")
                filename = f"transcript_{date_tag}_{job_id}.md"

                out_path = RESULTS_DIR / f"{job_id}_transcript.md"
                out_path.write_text(md_content, encoding="utf-8")

                # Send via Telegram
                duration_str = _fmt_duration(data["duration_seconds"])
                speakers_count = data["speakers_count"]

                await bot.send_document(
                    chat_id=chat_id,
                    document=BufferedInputFile(md_content.encode("utf-8"), filename=filename),
                    caption=(
                        f"✅ Готово! Транскрипция звонка #{job_id}\n"
                        f"📊 Длительность: {duration_str}\n"
                        f"👥 Спикеров: {speakers_count}"
                    ),
                )
                logger.info("Job %d sent to chat %d as %s", job_id, chat_id, filename)

                await _set_status(job_id, "done")

            except Exception as exc:
                logger.error("Sender job %s failed: %s",
                             job["id"] if job else "?", exc, exc_info=True)
                if job:
                    await _set_status(job["id"], "error", str(exc))

            await asyncio.sleep(POLL_INTERVAL)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(run_worker())
