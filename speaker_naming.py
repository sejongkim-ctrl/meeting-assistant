"""
화자 이름 추론 (Phase 2)

2단계 파이프라인:
  1단계: 한국어 호칭 패턴 regex
         - "철수야" → 다음 발화자 = 철수
         - "저는 박팀장입니다" → 현재 화자 = 박팀장
  2단계: Gemini 2.5 Flash로 전체 스크립트 분석 (regex 결과 보완)

반환값:
  {speaker_id: name}
  예: {"SPEAKER_00": "김대리", "SPEAKER_01": "박팀장 (추정)"}
"""

import re
import os
import json
from typing import Optional


# ---------------------------------------------------------------------------
# 한국어 호칭 패턴 (우선순위 순)
# ---------------------------------------------------------------------------
_PATTERNS = [
    # 자기소개: "저는 홍길동입니다/인데요/이고요"
    (r"(?:저는|제 이름은|저를)\s*([가-힣]{2,4})\s*(?:입니다|인데|이고|이에요|예요|라고|이라고)", "self_intro"),
    # 직함 호칭: "김 팀장님", "박 과장님", "이 대리님"
    (r"([가-힣])\s*([가-힣]{2,4}님)\s*[,。\s]", "title_full"),
    # 이름 호칭: "철수야", "영희야", "민준아"
    (r"([가-힣]{2,4})\s*(?:야|아)\s*[,。\s]", "called"),
    # 존칭: "홍길동 씨", "홍길동 님"
    (r"([가-힣]{2,4})\s+(?:씨|님)\s*[,。\s]", "honorific"),
]


def _extract_names_from_text(text: str) -> dict[str, list[str]]:
    """텍스트에서 패턴별 이름 추출. {pattern_type: [names]}"""
    found: dict[str, list[str]] = {}
    for pattern, ptype in _PATTERNS:
        for m in re.finditer(pattern, text):
            # title_full은 그룹 1+2 합산
            if ptype == "title_full":
                name = m.group(1) + m.group(2).rstrip("님") + "님"
            else:
                name = m.group(1)
            if 2 <= len(name) <= 5:
                found.setdefault(ptype, []).append(name)
    return found


def infer_speaker_names(
    script: list[dict],
    gemini_api_key: Optional[str] = None,
) -> dict[str, str]:
    """
    화자 ID → 이름 매핑 추론.

    Args:
        script: diarization.transcribe_segments() 결과
                [{speaker, text, time, ...}]
        gemini_api_key: Gemini API 키 (없으면 env에서 읽음)

    Returns:
        {speaker_id: inferred_name}
        이름을 알 수 없으면 원래 speaker_id 유지
    """
    speakers = sorted({seg["speaker"] for seg in script})
    mapping: dict[str, str] = {sp: sp for sp in speakers}

    if not script:
        return mapping

    # ------------------------------------------------------------------
    # 1단계: regex 분석
    # ------------------------------------------------------------------

    # 자기소개 패턴: 현재 화자 = 이름
    for seg in script:
        extracted = _extract_names_from_text(seg["text"])
        if "self_intro" in extracted:
            name = extracted["self_intro"][0]
            if mapping.get(seg["speaker"]) == seg["speaker"]:
                mapping[seg["speaker"]] = name

    # 호칭 패턴: A가 "철수야" → 다음 발화자(B)가 철수
    for i, seg in enumerate(script[:-1]):
        next_seg = script[i + 1]
        if next_seg["speaker"] == seg["speaker"]:
            continue  # 같은 화자 연속 발화는 스킵

        extracted = _extract_names_from_text(seg["text"])
        called = extracted.get("called", []) + extracted.get("honorific", [])
        if called and mapping.get(next_seg["speaker"]) == next_seg["speaker"]:
            mapping[next_seg["speaker"]] = called[-1]

    # ------------------------------------------------------------------
    # 2단계: Gemini Flash로 보완 (regex 미해결 화자 존재 시)
    # ------------------------------------------------------------------
    unresolved = [sp for sp, name in mapping.items() if name == sp]
    if unresolved:
        api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
        if api_key and len(script) >= 3:
            try:
                gemini_result = _infer_with_gemini(script, mapping, api_key)
                mapping.update(gemini_result)
            except Exception:
                pass  # Gemini 실패 시 regex 결과 유지

    return mapping


def _infer_with_gemini(
    script: list[dict],
    current_mapping: dict[str, str],
    api_key: str,
) -> dict[str, str]:
    """Gemini 2.5 Flash로 화자 이름 추론."""
    from google import genai

    client = genai.Client(api_key=api_key)

    # 스크립트 최대 8000자
    script_text = "\n".join(
        f"[{seg['speaker']}] {seg['text']}" for seg in script[:120]
    )[:8000]

    speakers_json = json.dumps(
        {sp: name for sp, name in current_mapping.items()}, ensure_ascii=False
    )

    prompt = f"""아래 회의 스크립트에서 각 화자(SPEAKER_XX)의 실제 이름이나 직함을 추론하세요.

## 현재까지 파악된 이름 (regex 1단계 결과)
{speakers_json}

## 스크립트
{script_text}

## 지시사항
- 아직 이름을 모르는 화자(SPEAKER_XX 그대로인 경우)에 대해서만 추론하세요.
- 스크립트에서 호칭, 자기소개, 대화 맥락을 근거로 판단하세요.
- 확신도 70% 미만이면 이름 뒤에 " (추정)"을 추가하세요.
- 전혀 파악 불가능하면 원래 SPEAKER_XX를 그대로 두세요.
- 추론에 사용한 근거 문장을 짧게 함께 적어주세요.

## 출력 형식 (JSON만 출력, 주석/설명 불필요)
{{"SPEAKER_00": "이름", "SPEAKER_01": "이름 (추정)"}}"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )

    raw = response.text.strip()
    # 코드블록 제거
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    inferred: dict[str, str] = json.loads(raw.strip())

    # 이미 이름이 있는 화자는 덮어쓰지 않음
    result = {}
    for sp, name in inferred.items():
        if sp in current_mapping and current_mapping[sp] == sp:
            result[sp] = name

    return result


def apply_names_to_script(
    script: list[dict],
    mapping: dict[str, str],
) -> list[dict]:
    """
    스크립트의 speaker 필드를 추론된 이름으로 교체.

    Returns:
        speaker_label 필드가 추가된 스크립트
    """
    result = []
    for seg in script:
        updated = dict(seg)
        updated["speaker_label"] = mapping.get(seg["speaker"], seg["speaker"])
        result.append(updated)
    return result


def format_labeled_transcript(
    script: list[dict],
    mapping: dict[str, str],
) -> str:
    """화자 이름 포함 텍스트 녹취록 생성."""
    lines = []
    for seg in script:
        label = mapping.get(seg["speaker"], seg["speaker"])
        lines.append(f"[{seg.get('time', '')}] {label}: {seg['text']}")
    return "\n".join(lines)
