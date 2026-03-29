"""Recording start/stop/status endpoints."""

import asyncio
import os
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter

from backend.models import RecordingStartRequest, RecordingStatusResponse, RecordingStopResponse
from backend.ws_manager import manager

router = APIRouter()

# Module-level active engines keyed by session_id
_active_engines: dict[str, object] = {}
_polling_tasks: dict[str, asyncio.Task] = {}

_SESSION_KEY = "default"


async def _poll_transcription(engine):
    """Poll engine for new segments and broadcast via WebSocket."""
    seen_count = 0
    while engine.is_active:
        await asyncio.sleep(2)
        segments = engine.get_transcript_segments()
        if len(segments) > seen_count:
            new_segs = segments[seen_count:]
            seen_count = len(segments)
            for seg in new_segs:
                await manager.broadcast({
                    "type": "transcript",
                    "text": seg.get("text", ""),
                    "speaker": seg.get("speaker", ""),
                    "time": seg.get("time", ""),
                })
    # Broadcast final segments after stop
    segments = engine.get_transcript_segments()
    if len(segments) > seen_count:
        for seg in segments[seen_count:]:
            await manager.broadcast({
                "type": "transcript",
                "text": seg.get("text", ""),
                "speaker": seg.get("speaker", ""),
                "time": seg.get("time", ""),
            })
    await manager.broadcast({"type": "recording_stopped", "data": {"segment_count": len(segments)}})


@router.post("/start")
async def start_recording(body: RecordingStartRequest):
    from meeting_engine import MeetingEngine

    if _SESSION_KEY in _active_engines:
        eng = _active_engines[_SESSION_KEY]
        if eng.is_active:
            return {"status": "already_recording"}

    # Set API key in env if provided
    if body.api_key:
        os.environ["GEMINI_API_KEY"] = body.api_key

    engine = MeetingEngine(stt_engine="local-whisper", interval=5)
    engine.start()
    _active_engines[_SESSION_KEY] = engine

    # Start polling task
    task = asyncio.create_task(_poll_transcription(engine))
    _polling_tasks[_SESSION_KEY] = task

    return {"status": "started", "session_id": _SESSION_KEY}


@router.post("/stop", response_model=RecordingStopResponse)
async def stop_recording():
    engine = _active_engines.get(_SESSION_KEY)
    if engine is None or not engine.is_active:
        return RecordingStopResponse(wav_path=None, transcript=[], duration="00:00:00")

    duration = engine.get_elapsed_time()
    engine.stop()

    # Save WAV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _project_root = Path(__file__).parent.parent.parent
    wav_dir = _project_root / "meetings" / timestamp
    wav_dir.mkdir(parents=True, exist_ok=True)
    wav_path = str(wav_dir / "recording.wav")
    engine.save_full_wav(wav_path)

    transcript = engine.get_transcript_segments()

    # Cancel polling task
    task = _polling_tasks.pop(_SESSION_KEY, None)
    if task and not task.done():
        task.cancel()

    _active_engines.pop(_SESSION_KEY, None)

    return RecordingStopResponse(
        wav_path=wav_path,
        transcript=transcript,
        duration=duration,
    )


@router.get("/status", response_model=RecordingStatusResponse)
async def recording_status():
    engine = _active_engines.get(_SESSION_KEY)
    if engine is None or not engine.is_active:
        return RecordingStatusResponse(is_recording=False, duration="00:00:00", segment_count=0)

    return RecordingStatusResponse(
        is_recording=True,
        duration=engine.get_elapsed_time(),
        segment_count=len(engine.get_transcript_segments()),
    )
