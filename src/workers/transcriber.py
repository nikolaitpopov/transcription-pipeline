"""
Task 02 — Transcription worker.

Polls the jobs queue for pending entries, transcribes audio with faster-whisper
in a thread (ThreadPoolExecutor) and saves the result as JSON.
Model is loaded once at startup and reused for all jobs.
"""

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from src.config import DATA_DIR, DB_PATH

logger = logging.getLogger(__name__)

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3-turbo")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")

TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
POLL_INTERVAL = 5  # seconds

# Global model instance — loaded once, reused for all jobs
_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        logger.info("Loading Whisper model %s on %s...", WHISPER_MODEL, WHISPER_DEVICE)
        _model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
        logger.info("Whisper model loaded.")
    return _model


# ── Transcription (runs in a thread) ─────────────────────────────────────────

def _transcribe_sync(audio_path: str, job_id: int) -> dict:
    """
    Runs inside ThreadPoolExecutor — no async here.
    Uses global model instance to avoid reloading on every job.
    """
    model = _get_model()

    segments_iter, info = model.transcribe(
        audio_path,
        language="ru",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        word_timestamps=False,
    )

    segments = [
        {"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()}
        for s in segments_iter
    ]

    return {
        "job_id": job_id,
        "duration_seconds": round(info.duration, 3),
        "language": info.language,
        "segments": segments,
    }


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _fetch_pending_job() -> dict | None:
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
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
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Transcription worker started (model=%s device=%s)",
        WHISPER_MODEL, WHISPER_DEVICE,
    )

    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1)

    # Preload model at startup
    await loop.run_in_executor(executor, _get_model)

    while True:
        job = None
        try:
            job = await _fetch_pending_job()
            if job is None:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            job_id = job["id"]
            audio_path = job["file_path"]
            logger.info("Processing job %d: %s", job_id, audio_path)

            await _set_status(job_id, "transcribing")

            # Run blocking transcription in a thread (inherits env vars unlike subprocess)
            result = await loop.run_in_executor(
                executor,
                _transcribe_sync,
                audio_path,
                job_id,
            )

            # Save JSON
            out_path = TRANSCRIPTS_DIR / f"{job_id}_whisper.json"
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(
                "Job %d transcribed: %d segments, duration=%.1fs → %s",
                job_id, len(result["segments"]), result["duration_seconds"], out_path,
            )

            await _set_status(job_id, "transcribed")

        except Exception as exc:
            logger.error("Job %s failed: %s", job.get("id") if job else "?", exc, exc_info=True)
            if job:
                await _set_status(job["id"], "error", str(exc))

        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(run_worker())
