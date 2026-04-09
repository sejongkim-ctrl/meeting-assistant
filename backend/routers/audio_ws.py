"""WebSocket endpoint: receive browser PCM audio, transcribe via Gemini."""
import asyncio
import io
import sys
import wave
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.ws_manager import manager

router = APIRouter()

SAMPLE_RATE = 16000
CHUNK_DURATION_SEC = 5
CHUNK_BYTES = SAMPLE_RATE * 2 * CHUNK_DURATION_SEC  # 160,000 bytes per chunk


def _pcm_to_wav(pcm_bytes: bytes) -> bytes:
    """Wrap raw 16-bit mono PCM bytes in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


@router.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket):
    """Accept raw Int16 PCM from browser, buffer to 5s chunks, transcribe with Gemini."""
    await websocket.accept()

    from meeting_engine import Transcriber

    transcriber = Transcriber(engine="gemini")

    pcm_buffer = bytearray()
    all_pcm = bytearray()
    transcript_segments: list[dict] = []

    async def _transcribe_chunk(chunk_bytes: bytes, time_str: str) -> None:
        try:
            wav_bytes = _pcm_to_wav(chunk_bytes)
            loop = asyncio.get_running_loop()
            text = await loop.run_in_executor(None, transcriber.transcribe, wav_bytes)
            if text:
                seg = {"text": text, "speaker": "", "time": time_str}
                transcript_segments.append(seg)
                await manager.broadcast(
                    {"type": "transcript", "text": text, "speaker": "", "time": time_str}
                )
        except Exception as e:
            print(f"[audio_ws] transcribe error at {time_str}: {e}", file=sys.stderr)

    try:
        while True:
            data = await websocket.receive_bytes()
            pcm_buffer.extend(data)
            all_pcm.extend(data)

            # Transcribe when we have 5 seconds of audio
            while len(pcm_buffer) >= CHUNK_BYTES:
                chunk = bytes(pcm_buffer[:CHUNK_BYTES])
                pcm_buffer = pcm_buffer[CHUNK_BYTES:]
                time_str = datetime.now().strftime("%H:%M:%S")
                asyncio.create_task(_transcribe_chunk(chunk, time_str))

    except WebSocketDisconnect:
        pass
    finally:
        # Transcribe any remaining audio (at least 1 second)
        if len(pcm_buffer) >= SAMPLE_RATE * 2:
            time_str = datetime.now().strftime("%H:%M:%S")
            await _transcribe_chunk(bytes(pcm_buffer), time_str)

        # Save full recording as WAV
        wav_path = None
        if all_pcm:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            _project_root = Path(__file__).parent.parent.parent
            wav_dir = _project_root / "meetings" / timestamp
            wav_dir.mkdir(parents=True, exist_ok=True)
            wav_path = str(wav_dir / "recording.wav")
            with open(wav_path, "wb") as f:
                f.write(_pcm_to_wav(bytes(all_pcm)))

        await manager.broadcast(
            {
                "type": "recording_stopped",
                "data": {
                    "segment_count": len(transcript_segments),
                    "transcript": transcript_segments,
                    "wav_path": wav_path,
                },
            }
        )
