"""Diarization post-processing pipeline endpoint."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Depends, HTTPException
import aiosqlite

from backend.database import get_db
from backend.models import PostprocessRequest, PostprocessResponse

router = APIRouter()


@router.post("/{note_id}", response_model=PostprocessResponse)
async def run_postprocess(
    note_id: int,
    body: PostprocessRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    from diarization import run_postprocess
    from speaker_naming import infer_speaker_names, apply_names_to_script

    # Fetch note
    async with db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)) as cursor:
        note = await cursor.fetchone()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    wav_path = note["wav_path"]
    if not wav_path:
        raise HTTPException(status_code=400, detail="Note has no wav_path set")

    path = Path(wav_path)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"WAV file not found: {wav_path}")

    try:
        # Run blocking pipeline in thread pool
        import asyncio
        loop = asyncio.get_event_loop()
        script = await loop.run_in_executor(
            None,
            lambda: run_postprocess(wav_path, hf_token=body.hf_token),
        )

        mapping = await loop.run_in_executor(
            None,
            lambda: infer_speaker_names(script),
        )

        labeled_script = apply_names_to_script(script, mapping)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Update note in DB
    diarized_json = json.dumps(labeled_script, ensure_ascii=False)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE notes SET diarized_script = ?, updated_at = ? WHERE id = ?",
        (diarized_json, now, note_id),
    )
    await db.commit()

    return PostprocessResponse(
        status="completed",
        script=labeled_script,
        mapping=mapping,
    )
