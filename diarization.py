"""
화자 분리 후처리 파이프라인 (Phase 2)

흐름:
  recording.wav
    → pyannote.audio 3.1 (화자 구간 분리)
    → faster-whisper (구간별 재전사)
    → [{speaker, start, end, text, time}]

요구사항:
  - pip install pyannote.audio torch
  - .env에 HUGGINGFACE_TOKEN=hf_xxxx
  - HuggingFace에서 모델 사용 동의:
      https://hf.co/pyannote/speaker-diarization-3.1
"""

import os
import wave
import numpy as np
from typing import Optional


# 화자별 UI 색상 (6색 팔레트)
SPEAKER_COLORS = {
    0: "#4A90D9",  # 파랑
    1: "#E5734A",  # 주황
    2: "#5CB85C",  # 초록
    3: "#9B59B6",  # 보라
    4: "#F0AD4E",  # 노랑
    5: "#E74C3C",  # 빨강
}


def get_speaker_color(speaker_id: str) -> str:
    """SPEAKER_00 형식 ID에서 색상 반환."""
    try:
        idx = int(speaker_id.split("_")[-1])
    except (ValueError, IndexError):
        idx = 0
    return SPEAKER_COLORS.get(idx % len(SPEAKER_COLORS), "#7f8c8d")


def diarize(wav_path: str, hf_token: Optional[str] = None) -> list[dict]:
    """
    pyannote.audio 3.1로 화자 분리.

    Args:
        wav_path: 전체 녹음 WAV 파일 경로
        hf_token: HuggingFace 토큰 (없으면 env에서 읽음)

    Returns:
        list of {speaker: str, start: float, end: float}
    """
    try:
        from pyannote.audio import Pipeline
        import torch
    except ImportError:
        raise RuntimeError(
            "pyannote.audio가 설치되지 않았습니다.\n"
            "pip install pyannote.audio torch"
        )

    token = hf_token or os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")
    if not token:
        raise ValueError(
            "HuggingFace 토큰이 없습니다.\n"
            ".env에 HUGGINGFACE_TOKEN=hf_xxxx 추가 후 재시도하세요.\n"
            "토큰 발급: https://hf.co/settings/tokens\n"
            "모델 사용 동의: https://hf.co/pyannote/speaker-diarization-3.1"
        )

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=token,
    )
    # MPS 일부 연산 미지원 → CPU 명시
    pipeline.to(torch.device("cpu"))

    diarization = pipeline(wav_path)

    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append({
            "speaker": speaker,
            "start": round(turn.start, 3),
            "end": round(turn.end, 3),
        })

    return segments


def transcribe_segments(
    wav_path: str,
    segments: list[dict],
    whisper_model=None,
    language: str = "ko",
) -> list[dict]:
    """
    화자 구간별 faster-whisper 재전사.

    Args:
        wav_path: 전체 녹음 WAV 파일 경로
        segments: diarize() 반환값
        whisper_model: 기존 WhisperModel 인스턴스 (없으면 새로 로드)
        language: 전사 언어

    Returns:
        list of {speaker, start, end, text, time, color}
    """
    from faster_whisper import WhisperModel

    if whisper_model is None:
        whisper_model = WhisperModel("small", device="cpu", compute_type="int8")

    # WAV 전체 로드
    with wave.open(wav_path, "rb") as wf:
        sr = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    audio_full = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    result = []
    for seg in segments:
        start_idx = int(seg["start"] * sr)
        end_idx = int(seg["end"] * sr)
        chunk = audio_full[start_idx:end_idx]

        if len(chunk) < sr * 0.3:  # 0.3초 미만 구간 스킵
            continue

        whisper_segs, _ = whisper_model.transcribe(
            chunk,
            language=language,
            beam_size=5,
        )
        text = " ".join(s.text.strip() for s in whisper_segs).strip()
        if not text:
            continue

        # 시작 시간 HH:MM:SS 변환
        start_sec = int(seg["start"])
        time_str = (
            f"{start_sec // 3600:02d}:"
            f"{(start_sec % 3600) // 60:02d}:"
            f"{start_sec % 60:02d}"
        )

        result.append({
            "speaker": seg["speaker"],
            "start": seg["start"],
            "end": seg["end"],
            "text": text,
            "time": time_str,
            "color": get_speaker_color(seg["speaker"]),
        })

    return result


def run_postprocess(
    wav_path: str,
    hf_token: Optional[str] = None,
    whisper_model=None,
    progress_callback=None,
) -> list[dict]:
    """
    전체 후처리 파이프라인 실행 (diarize → transcribe).

    Args:
        wav_path: recording.wav 경로
        hf_token: HuggingFace 토큰
        whisper_model: 재사용할 WhisperModel 인스턴스
        progress_callback: (step: str, pct: float) → None

    Returns:
        화자별 전사 결과 list
    """
    if progress_callback:
        progress_callback("화자 분리 중...", 0.1)

    segments = diarize(wav_path, hf_token=hf_token)

    if progress_callback:
        progress_callback(f"화자 {len(set(s['speaker'] for s in segments))}명 감지. 구간별 재전사 중...", 0.5)

    result = transcribe_segments(wav_path, segments, whisper_model=whisper_model)

    if progress_callback:
        progress_callback("완료", 1.0)

    return result


def get_wav_duration(wav_path: str) -> float:
    """WAV 파일 길이(초) 반환."""
    with wave.open(wav_path, "rb") as wf:
        return wf.getnframes() / wf.getframerate()
