"""
Task 03 — Diarization worker.

Polls for jobs with status='transcribed', runs pyannote.audio speaker diarization,
merges with Whisper segments and saves combined JSON.
"""

import asyncio
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from src.config import DATA_DIR, DB_PATH

logger = logging.getLogger(__name__)

HUGGINGFACE_TOKEN = os.getenv("HUGGINGFACE_TOKEN")
DIARIZE_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")  # reuse same env var
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
POLL_INTERVAL = 5  # seconds


# ── Speaker normalization ─────────────────────────────────────────────────────

def _normalize_speaker(label: str) -> str:
    """'SPEAKER_00' → 'Спикер 1', 'SPEAKER_01' → 'Спикер 2', etc."""
    try:
        idx = int(label.split("_")[-1])
        return f"Спикер {idx + 1}"
    except (ValueError, IndexError):
        return label


# ── Merge logic ───────────────────────────────────────────────────────────────

def _assign_speaker(seg_start: float, seg_end: float, diarization: list[dict]) -> str:
    best_speaker = "Неизвестно"
    best_overlap = 0.0
    for d in diarization:
        overlap = min(seg_end, d["end"]) - max(seg_start, d["start"])
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = d["speaker"]
    return best_speaker


def _merge_turns(turns: list[dict], gap_threshold: float = 1.5) -> list[dict]:
    """Merge consecutive turns from the same speaker with gap < gap_threshold."""
    if not turns:
        return []
    merged = [turns[0].copy()]
    for turn in turns[1:]:
        prev = merged[-1]
        gap = turn["start"] - prev["end"]
        if turn["speaker"] == prev["speaker"] and gap < gap_threshold:
            prev["end"] = turn["end"]
            prev["text"] = prev["text"].rstrip() + " " + turn["text"].lstrip()
        else:
            merged.append(turn.copy())
    return merged


# ── Core diarization (runs in subprocess) ────────────────────────────────────

def _diarize_sync(audio_path: str, job_id: int, whisper_json_path: str) -> dict:
    import torch
    from pyannote.audio import Pipeline

    # Load Whisper transcript
    with open(whisper_json_path, encoding="utf-8") as f:
        whisper = json.load(f)

    # Run diarization
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token=HUGGINGFACE_TOKEN,
    )
    device = "cuda" if DIARIZE_DEVICE == "cuda" and torch.cuda.is_available() else "cpu"
    pipeline.to(torch.device(device))

    import torch
    import soundfile as sf
    samples, sample_rate = sf.read(audio_path, dtype="float32", always_2d=True)
    waveform = torch.from_numpy(samples.T)
    audio_dict = {"waveform": waveform, "sample_rate": sample_rate}
    diarization_result = pipeline(audio_dict)

    # Convert pyannote output to list of dicts with normalized speaker names
    annotation = diarization_result.speaker_diarization
    diarization_segments = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        diarization_segments.append({
            "start": round(turn.start, 3),
            "end": round(turn.end, 3),
            "speaker": _normalize_speaker(speaker),
        })

    # Assign speaker to each Whisper segment
    turns = []
    for seg in whisper["segments"]:
        speaker = _assign_speaker(seg["start"], seg["end"], diarization_segments)
        turns.append({
            "start": seg["start"],
            "end": seg["end"],
            "speaker": speaker,
            "text": seg["text"],
        })

    # Merge consecutive same-speaker turns
    turns = _merge_turns(turns)

    speakers = sorted({t["speaker"] for t in turns})

    return {
        "job_id": job_id,
        "duration_seconds": whisper["duration_seconds"],
        "speakers_count": len(speakers),
        "turns": turns,
    }


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _fetch_transcribed_job() -> dict | None:
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM jobs WHERE status='transcribed' ORDER BY created_at ASC LIMIT 1"
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
    logger.info("Diarization worker started (device=%s)", DIARIZE_DEVICE)

    loop = asyncio.get_running_loop()
    executor = ProcessPoolExecutor(max_workers=1)

    while True:
        job = None
        try:
            job = await _fetch_transcribed_job()
            if job is None:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            job_id = job["id"]
            audio_path = job["file_path"]
            whisper_path = str(TRANSCRIPTS_DIR / f"{job_id}_whisper.json")
            logger.info("Diarizing job %d: %s", job_id, audio_path)

            await _set_status(job_id, "diarizing")

            result = await loop.run_in_executor(
                executor,
                _diarize_sync,
                audio_path,
                job_id,
                whisper_path,
            )

            out_path = TRANSCRIPTS_DIR / f"{job_id}_diarized.json"
            out_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info(
                "Job %d diarized: %d turns, %d speakers → %s",
                job_id, len(result["turns"]), result["speakers_count"], out_path,
            )

            await _set_status(job_id, "diarized")

        except Exception as exc:
            logger.error("Diarization job %s failed: %s",
                         job["id"] if job else "?", exc, exc_info=True)
            if job:
                await _set_status(job["id"], "error", str(exc))

        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(run_worker())
