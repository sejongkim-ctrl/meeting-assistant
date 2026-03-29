"""AI document generation endpoint."""

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
from backend.models import GenerateRequest, GenerateResult

router = APIRouter()

TEMPLATE_PROMPTS: dict[str, str] = {
    "summary": (
        "아래 녹취록을 A4 한 페이지 분량(500자 내외)의 핵심 요약으로 작성하세요. "
        "주요 결정사항, 액션아이템, 다음 단계를 포함하세요."
    ),
    "minutes": (
        "아래 녹취록을 구조화된 공식 회의록으로 작성하세요. "
        "참석자, 안건, 논의내용, 결정사항, 액션아이템(담당자·기한 포함)을 포함하세요."
    ),
    "lecture": (
        "아래 녹취록을 학습용 강의 노트로 정리하세요. "
        "핵심 개념, 예시, 중요 포인트를 구조화하여 작성하세요."
    ),
    "ir": (
        "아래 녹취록을 투자자용 IR 피칭 문서로 재구성하세요. "
        "문제정의, 솔루션, 시장규모, 비즈니스 모델, 팀, 요청사항 순으로 작성하세요."
    ),
    "agm": (
        "아래 녹취록을 주주총회 의사록 형식으로 작성하세요. "
        "개회 선언, 안건별 심의·결의 내용, 폐회 순으로 공식 문서 형태로 작성하세요."
    ),
    "sales": (
        "아래 녹취록을 세일즈 미팅 노트로 정리하세요. "
        "고객 니즈, 페인포인트, 제안 내용, 다음 액션을 중심으로 작성하세요."
    ),
    "interview": (
        "아래 녹취록을 채용 인터뷰 평가 노트로 정리하세요. "
        "지원자 답변 요약, 역량 평가, 강점/약점, 종합 의견을 포함하세요."
    ),
    "free": (
        "아래 녹취록을 보기 좋게 정리해주세요. "
        "내용의 특성에 맞게 가장 적합한 형식을 자유롭게 선택하세요."
    ),
}


def _build_transcript_text(note_row: aiosqlite.Row) -> str:
    """diarized_script 우선, 없으면 transcript 사용."""
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


@router.post("", response_model=GenerateResult)
async def generate_document(
    body: GenerateRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute("SELECT * FROM notes WHERE id = ?", (body.note_id,)) as cursor:
        note = await cursor.fetchone()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    transcript_text = _build_transcript_text(note)
    if not transcript_text.strip():
        raise HTTPException(status_code=400, detail="Note has no transcript content")

    template_instruction = TEMPLATE_PROMPTS.get(
        body.template,
        TEMPLATE_PROMPTS["free"],
    )

    api_key = body.api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY not set")

    prompt = f"""{template_instruction}

## 녹취록
{transcript_text}

## 지시사항
- 녹취록에 있는 내용만 사용하세요. 없는 내용을 추가하거나 추측하지 마세요.
- 한국어로 작성하세요.
- 마크다운 형식으로 구조화하세요.
"""

    client = genai.Client(api_key=api_key)

    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        ),
    )

    return GenerateResult(content=response.text.strip())
