"""AI Q&A chat endpoint — answers questions about a specific note."""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Depends, HTTPException
from google import genai
import aiosqlite

from backend.database import get_db
from backend.models import ChatRequest, ChatResponse

router = APIRouter()

SYSTEM_PROMPT = (
    "당신은 회의록 분석 AI 어시스턴트입니다. "
    "아래 회의 녹취록을 기반으로 사용자의 질문에 답하세요. "
    "녹취록에 없는 내용은 추측하지 말고, 근거를 명확히 제시하세요. "
    "한국어로 답변하세요."
)


def _build_transcript_text(note_row: aiosqlite.Row) -> str:
    def parse(val):
        if val is None:
            return None
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return None
        return val

    diarized = parse(note_row["diarized_script"])
    if diarized and isinstance(diarized, list):
        lines = []
        for seg in diarized:
            label = seg.get("speaker_label") or seg.get("speaker", "")
            time = seg.get("time", "")
            text = seg.get("text", "")
            lines.append(f"[{time}] {label}: {text}")
        return "\n".join(lines)

    transcript = parse(note_row["transcript"])
    if transcript and isinstance(transcript, list):
        lines = []
        for seg in transcript:
            time = seg.get("time", "")
            text = seg.get("text", "")
            lines.append(f"[{time}] {text}")
        return "\n".join(lines)

    if isinstance(note_row["transcript"], str):
        return note_row["transcript"]

    return ""


@router.post("/chat", response_model=ChatResponse)
async def chat_with_note(
    body: ChatRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute("SELECT * FROM notes WHERE id = ?", (body.note_id,)) as cursor:
        note = await cursor.fetchone()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    transcript_text = _build_transcript_text(note)

    api_key = body.api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY not set")

    # Build Gemini conversation history
    # First message includes the transcript as context
    gemini_contents = []

    if transcript_text.strip():
        # Prepend context to the first user message
        first_user_idx = next(
            (i for i, m in enumerate(body.messages) if m.role == "user"), None
        )
        for i, msg in enumerate(body.messages):
            role = "user" if msg.role == "user" else "model"
            content = msg.content
            if i == first_user_idx and transcript_text.strip():
                content = (
                    f"{SYSTEM_PROMPT}\n\n"
                    f"## 회의 녹취록\n{transcript_text}\n\n"
                    f"## 질문\n{msg.content}"
                )
                first_user_idx = None  # only prepend once
            gemini_contents.append({"role": role, "parts": [{"text": content}]})
    else:
        for msg in body.messages:
            role = "user" if msg.role == "user" else "model"
            gemini_contents.append({"role": role, "parts": [{"text": msg.content}]})

    client = genai.Client(api_key=api_key)
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(
            model="gemini-2.5-flash",
            contents=gemini_contents,
        ),
    )

    return ChatResponse(content=response.text.strip())
