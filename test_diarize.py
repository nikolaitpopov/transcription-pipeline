"""Quick test: run diarization directly (no subprocess) to see logs."""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

HUGGINGFACE_TOKEN = os.getenv("HUGGINGFACE_TOKEN")
audio_path = str(next(Path("data/audio/inbox").glob("*.ogg")))
print(f"Audio: {audio_path}")

import torch
import soundfile as sf
from pyannote.audio import Pipeline

print("Loading pipeline...")
pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    token=HUGGINGFACE_TOKEN,
)
print("Device: cpu")
pipeline.to(torch.device("cpu"))

print("Running diarization...")
# Load audio with soundfile (no FFmpeg/torchcodec dependency)
samples, sample_rate = sf.read(audio_path, dtype="float32", always_2d=True)
waveform = torch.from_numpy(samples.T)  # (channels, time)
audio_dict = {"waveform": waveform, "sample_rate": sample_rate}
result = pipeline(audio_dict)

print("Result:")
annotation = result.speaker_diarization
for turn, _, speaker in annotation.itertracks(yield_label=True):
    print(f"  {turn.start:.1f}s - {turn.end:.1f}s : {speaker}")
