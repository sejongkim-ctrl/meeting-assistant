"""CRUD endpoints for folders and notes."""

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
import aiosqlite

from backend.database import get_db
import uuid as _uuid

from backend.models import (
    FolderCreate, FolderOut,
    NoteCreate, NoteUpdate, NoteOut,
    NoteSearchResult, ShareResponse,
)

router = APIRouter()


def _row_to_folder(row: aiosqlite.Row) -> FolderOut:
    return FolderOut(
        id=row["id"],
        name=row["name"],
        created_at=row["created_at"],
    )


def _row_to_note(row: aiosqlite.Row) -> NoteOut:
    def parse_json(val):
        if val is None:
            return None
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return val
        return val

    return NoteOut(
        id=row["id"],
        folder_id=row["folder_id"],
        title=row["title"],
        transcript=parse_json(row["transcript"]),
        diarized_script=parse_json(row["diarized_script"]),
        summary=row["summary"],
        wav_path=row["wav_path"],
        generated_docs=parse_json(row["generated_docs"]) if "generated_docs" in row.keys() else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------

@router.get("/folders", response_model=list[FolderOut])
async def list_folders(db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT * FROM folders ORDER BY created_at DESC") as cursor:
        rows = await cursor.fetchall()
    return [_row_to_folder(r) for r in rows]


@router.post("/folders", response_model=FolderOut, status_code=201)
async def create_folder(body: FolderCreate, db: aiosqlite.Connection = Depends(get_db)):
    now = datetime.now(timezone.utc).isoformat()
    async with db.execute(
        "INSERT INTO folders (name, created_at) VALUES (?, ?)",
        (body.name, now),
    ) as cursor:
        folder_id = cursor.lastrowid
    await db.commit()
    async with db.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)) as cursor:
        row = await cursor.fetchone()
    return _row_to_folder(row)


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

@router.get("/notes", response_model=list[NoteOut])
async def list_notes(
    folder_id: Optional[int] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    if folder_id is not None:
        async with db.execute(
            "SELECT * FROM notes WHERE folder_id = ? ORDER BY created_at DESC",
            (folder_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    else:
        async with db.execute("SELECT * FROM notes ORDER BY created_at DESC") as cursor:
            rows = await cursor.fetchall()
    return [_row_to_note(r) for r in rows]


@router.post("/notes", response_model=NoteOut, status_code=201)
async def create_note(body: NoteCreate, db: aiosqlite.Connection = Depends(get_db)):
    now = datetime.now(timezone.utc).isoformat()
    transcript_json = json.dumps(body.transcript, ensure_ascii=False) if body.transcript is not None else None
    diarized_json = json.dumps(body.diarized_script, ensure_ascii=False) if body.diarized_script is not None else None
    async with db.execute(
        """INSERT INTO notes (folder_id, title, transcript, diarized_script, summary, wav_path, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (body.folder_id, body.title, transcript_json, diarized_json, body.summary, body.wav_path, now, now),
    ) as cursor:
        note_id = cursor.lastrowid
    # FTS sync — commit once after both inserts for atomicity
    transcript_text = ""
    if body.transcript:
        segs = body.transcript if isinstance(body.transcript, list) else []
        transcript_text = " ".join(s.get("text", "") if isinstance(s, dict) else "" for s in segs)
    await db.execute(
        "INSERT INTO notes_fts(rowid, title, summary, transcript_text, note_id) VALUES (?, ?, ?, ?, ?)",
        (note_id, body.title, body.summary or "", transcript_text, note_id),
    )
    await db.commit()
    async with db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)) as cursor:
        row = await cursor.fetchone()
    return _row_to_note(row)


@router.get("/notes/search", response_model=list[NoteSearchResult])
async def search_notes(q: str = "", db: aiosqlite.Connection = Depends(get_db)):
    if not q.strip():
        return []
    fts_query = q.strip()
    async with db.execute(
        """SELECT n.id, n.title, n.summary, n.transcript, n.updated_at
           FROM notes n
           WHERE n.id IN (
               SELECT note_id FROM notes_fts WHERE notes_fts MATCH ?
           )
           ORDER BY n.updated_at DESC
           LIMIT 20""",
        (fts_query,),
    ) as cursor:
        rows = await cursor.fetchall()

    results = []
    for row in rows:
        snippet = ""
        if row["summary"]:
            idx = row["summary"].lower().find(q.lower())
            if idx >= 0:
                start = max(0, idx - 30)
                end = min(len(row["summary"]), idx + 70)
                snippet = ("..." if start > 0 else "") + row["summary"][start:end] + ("..." if end < len(row["summary"]) else "")
            else:
                snippet = row["summary"][:100]
        elif row["transcript"]:
            try:
                segs_raw = row["transcript"]
                segs = json.loads(segs_raw) if isinstance(segs_raw, str) else segs_raw
                if isinstance(segs, list):
                    full_text = " ".join(s.get("text", "") for s in segs)
                    idx = full_text.lower().find(q.lower())
                    if idx >= 0:
                        start = max(0, idx - 30)
                        end = min(len(full_text), idx + 70)
                        snippet = ("..." if start > 0 else "") + full_text[start:end] + ("..." if end < len(full_text) else "")
                    else:
                        snippet = full_text[:100]
            except Exception:
                snippet = ""
        results.append(NoteSearchResult(id=row["id"], title=row["title"], snippet=snippet, updated_at=row["updated_at"]))
    return results


@router.get("/notes/{note_id}", response_model=NoteOut)
async def get_note(note_id: int, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return _row_to_note(row)


@router.put("/notes/{note_id}", response_model=NoteOut)
async def update_note(note_id: int, body: NoteUpdate, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)) as cursor:
        existing = await cursor.fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Note not found")

    now = datetime.now(timezone.utc).isoformat()
    updates = {"updated_at": now}
    if body.folder_id is not None:
        updates["folder_id"] = body.folder_id
    if body.title is not None:
        updates["title"] = body.title
    if body.transcript is not None:
        updates["transcript"] = json.dumps(body.transcript, ensure_ascii=False)
    if body.diarized_script is not None:
        updates["diarized_script"] = json.dumps(body.diarized_script, ensure_ascii=False)
    if body.summary is not None:
        updates["summary"] = body.summary
    if body.wav_path is not None:
        updates["wav_path"] = body.wav_path
    if body.generated_docs is not None:
        updates["generated_docs"] = json.dumps(body.generated_docs, ensure_ascii=False)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [note_id]
    await db.execute(f"UPDATE notes SET {set_clause} WHERE id = ?", values)
    await db.commit()

    # FTS re-sync
    async with db.execute("SELECT title, summary, transcript FROM notes WHERE id = ?", (note_id,)) as cur:
        updated = await cur.fetchone()
    try:
        segs_raw = updated["transcript"]
        if segs_raw:
            segs = json.loads(segs_raw) if isinstance(segs_raw, str) else segs_raw
            t_text = " ".join(s.get("text", "") for s in segs if isinstance(s, dict))
        else:
            t_text = ""
    except Exception:
        t_text = ""
    await db.execute("DELETE FROM notes_fts WHERE note_id = ?", (note_id,))
    await db.execute(
        "INSERT INTO notes_fts(rowid, title, summary, transcript_text, note_id) VALUES (?, ?, ?, ?, ?)",
        (note_id, updated["title"], updated["summary"] or "", t_text, note_id),
    )
    await db.commit()

    async with db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)) as cursor:
        row = await cursor.fetchone()
    return _row_to_note(row)


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: int, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT id FROM notes WHERE id = ?", (note_id,)) as cursor:
        existing = await cursor.fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.execute("DELETE FROM notes_fts WHERE note_id = ?", (note_id,))
    await db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    await db.commit()


# ---------------------------------------------------------------------------
# Share
# ---------------------------------------------------------------------------

@router.post("/notes/{note_id}/share", response_model=ShareResponse)
async def share_note(note_id: int, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT id, share_token FROM notes WHERE id = ?", (note_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Note not found")
    token = row["share_token"] or str(_uuid.uuid4())
    await db.execute("UPDATE notes SET share_token = ? WHERE id = ?", (token, note_id))
    await db.commit()
    return ShareResponse(share_token=token)


@router.delete("/notes/{note_id}/share", status_code=204)
async def unshare_note(note_id: int, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT id FROM notes WHERE id = ?", (note_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.execute("UPDATE notes SET share_token = NULL WHERE id = ?", (note_id,))
    await db.commit()


@router.get("/shared/{token}", response_model=NoteOut)
async def get_shared_note(token: str, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT * FROM notes WHERE share_token = ?", (token,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Shared note not found")
    return _row_to_note(row)
