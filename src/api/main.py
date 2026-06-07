"""
HTTP API for transcription pipeline.

POST /jobs        — upload audio file, returns job_id
GET  /jobs/{id}   — get job status and result
GET  /jobs/{id}/file — download result .md file
"""

import logging
import shutil
from pathlib import Path
from datetime import datetime, timezone

import aiosqlite
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse

from src.config import DATA_DIR, DB_PATH, AUDIO_INBOX_DIR

logger = logging.getLogger(__name__)

app = FastAPI(title="Transcription Pipeline API")

TRANSCRIPTS_DIR = DATA_DIR / "transcripts"


@app.post("/jobs", status_code=201)
async def create_job(file: UploadFile = File(...)):
    """Upload audio file and create a transcription job."""
    # Validate extension
    suffix = Path(file.filename).suffix.lower().lstrip(".")
    allowed = {"mp3", "mp4", "m4a", "wav", "ogg", "webm", "flac"}
    if suffix not in allowed:
        raise HTTPException(400, f"Unsupported format: {suffix}. Allowed: {allowed}")

    # Save file
    AUDIO_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    dest = AUDIO_INBOX_DIR / file.filename
    # Avoid name collision
    counter = 1
    while dest.exists():
        dest = AUDIO_INBOX_DIR / f"{Path(file.filename).stem}_{counter}{Path(file.filename).suffix}"
        counter += 1

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # Insert job into DB
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO jobs (file_path, original_filename, telegram_chat_id, status, created_at, updated_at)
               VALUES (?, ?, ?, 'pending', ?, ?)""",
            (str(dest), file.filename, 0, now, now),
        )
        await db.commit()
        job_id = cursor.lastrowid

    logger.info("Created job %d for file %s", job_id, dest)
    return {"job_id": job_id, "status": "pending", "filename": file.filename}


@app.get("/jobs/{job_id}")
async def get_job(job_id: int):
    """Get job status. When done, includes path to result."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)) as cur:
            row = await cur.fetchone()

    if row is None:
        raise HTTPException(404, "Job not found")

    job = dict(row)
    result = {
        "job_id": job["id"],
        "status": job["status"],
        "filename": job["original_filename"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "error_message": job["error_message"],
    }

    # If done, check for result file
    if job["status"] == "done":
        md_path = TRANSCRIPTS_DIR / f"{job_id}_result.md"
        if md_path.exists():
            result["result_available"] = True
            result["download_url"] = f"/jobs/{job_id}/file"
        else:
            result["result_available"] = False

    return result


@app.get("/jobs/{job_id}/file")
async def download_result(job_id: int):
    """Download the result .md file."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)) as cur:
            row = await cur.fetchone()

    if row is None:
        raise HTTPException(404, "Job not found")

    job = dict(row)
    if job["status"] != "done":
        raise HTTPException(400, f"Job not done yet (status: {job['status']})")

    md_path = TRANSCRIPTS_DIR / f"{job_id}_result.md"
    if not md_path.exists():
        raise HTTPException(404, "Result file not found")

    return FileResponse(
        path=str(md_path),
        filename=f"{Path(job['original_filename']).stem}_transcript.md",
        media_type="text/markdown",
    )


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000)
