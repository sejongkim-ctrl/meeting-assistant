"""
AI Meeting Assistant Engine
- Audio recording (sounddevice)
- Speech-to-Text (Gemini / OpenAI Whisper / Groq Whisper)
- AI-powered meeting minutes & idea generation (Gemini)
"""

import io
import os
import wave
import time
import threading
import numpy as np
from datetime import datetime
from typing import Optional, Generator

import sounddevice as sd
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()


# ---------------------------------------------------------------------------
# Audio Recorder
# ---------------------------------------------------------------------------
class AudioRecorder:
    """Records audio from system microphone in a background thread."""

    SAMPLE_RATE = 16000
    CHANNELS = 1
    DTYPE = "float32"

    def __init__(self):
        self._buffer: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: Optional[sd.InputStream] = None
        self.is_recording = False
        self.current_rms: float = 0.0  # 실시간 볼륨 레벨 (0.0~1.0)

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[AudioRecorder] {status}")
        # 볼륨 레벨 갱신 (0~1 범위로 정규화, 0.1 이상이면 클리핑)
        rms = float(np.sqrt(np.mean(indata ** 2)))
        self.current_rms = min(rms / 0.1, 1.0)
        with self._lock:
            self._buffer.append(indata.copy())

    def start(self):
        self.is_recording = True
        self._stream = sd.InputStream(
            samplerate=self.SAMPLE_RATE,
            channels=self.CHANNELS,
            dtype=self.DTYPE,
            callback=self._callback,
            blocksize=int(self.SAMPLE_RATE * 0.5),  # 500ms blocks
        )
        self._stream.start()

    def stop(self):
        self.is_recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def get_chunk(self) -> Optional[np.ndarray]:
        """Extract and clear the audio buffer. Returns None if empty."""
        with self._lock:
            if not self._buffer:
                return None
            chunk = np.concatenate(self._buffer)
            self._buffer = []
        return chunk

    @staticmethod
    def to_wav_bytes(audio_np: np.ndarray, sample_rate: int = 16000) -> bytes:
        """Convert float32 numpy array to 16-bit PCM WAV bytes."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            pcm = (audio_np.flatten() * 32767).astype(np.int16)
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()

    @staticmethod
    def has_speech(audio_np: np.ndarray, threshold: float = 0.003) -> bool:
        """Simple VAD: True if RMS energy exceeds threshold."""
        rms = float(np.sqrt(np.mean(audio_np ** 2)))
        return rms > threshold


# ---------------------------------------------------------------------------
# Browser Audio Receiver (WebRTC)
# ---------------------------------------------------------------------------
class BrowserAudioReceiver:
    """Receives audio from browser via WebRTC. Drop-in replacement for AudioRecorder."""

    SAMPLE_RATE = 16000
    CHANNELS = 1

    def __init__(self):
        self._buffer: list[np.ndarray] = []
        self._lock = threading.Lock()
        self.is_recording = False
        self.current_rms: float = 0.0

    def push_audio(self, audio_np: np.ndarray):
        """WebRTC 콜백에서 호출. float32 16kHz mono 오디오를 버퍼에 추가."""
        rms = float(np.sqrt(np.mean(audio_np ** 2)))
        self.current_rms = min(rms / 0.1, 1.0)
        with self._lock:
            self._buffer.append(audio_np.copy())

    def start(self):
        self.is_recording = True

    def stop(self):
        self.is_recording = False

    def get_chunk(self) -> Optional[np.ndarray]:
        """Extract and clear the audio buffer. Returns None if empty."""
        with self._lock:
            if not self._buffer:
                return None
            chunk = np.concatenate(self._buffer)
            self._buffer = []
        return chunk

    @staticmethod
    def to_wav_bytes(audio_np: np.ndarray, sample_rate: int = 16000) -> bytes:
        return AudioRecorder.to_wav_bytes(audio_np, sample_rate)

    @staticmethod
    def has_speech(audio_np: np.ndarray, threshold: float = 0.003) -> bool:
        return AudioRecorder.has_speech(audio_np, threshold)


# ---------------------------------------------------------------------------
# Speech-to-Text
# ---------------------------------------------------------------------------
class Transcriber:
    """STT engine supporting Gemini Audio, OpenAI Whisper, Groq Whisper."""

    def __init__(self, engine: str = "gemini", dictionary: list[str] | None = None):
        self.engine = engine
        self.dictionary = dictionary or []

        if engine == "gemini":
            self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            self._model = "gemini-2.5-flash"

        elif engine == "openai":
            from openai import OpenAI
            self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        elif engine == "groq":
            from groq import Groq
            self._client = Groq(api_key=os.getenv("GROQ_API_KEY"))

        elif engine == "local-whisper":
            from faster_whisper import WhisperModel
            # small 모델: 480MB, M2 Pro CPU에서 실시간 3~5배 속도
            self._model = WhisperModel("small", device="cpu", compute_type="int8")

    def transcribe(self, wav_bytes: bytes) -> str:
        try:
            if self.engine == "gemini":
                return self._transcribe_gemini(wav_bytes)
            elif self.engine == "openai":
                return self._transcribe_openai(wav_bytes)
            elif self.engine == "groq":
                return self._transcribe_groq(wav_bytes)
            elif self.engine == "local-whisper":
                return self._transcribe_local_whisper(wav_bytes)
        except Exception as e:
            return f"[STT 오류: {str(e)[:80]}]"

    def _transcribe_gemini(self, wav_bytes: bytes) -> str:
        dict_hint = ""
        if self.dictionary:
            dict_hint = f"\n참고 용어: {', '.join(self.dictionary)}"
        response = self._client.models.generate_content(
            model=self._model,
            contents=[
                types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                "당신은 음성 전사(transcription) 전문가입니다.\n"
                "이 오디오에 사람의 말이 있으면 한국어로 정확하게 전사하세요.\n"
                "시간 정보 없이 텍스트만 출력하세요.\n\n"
                "## 절대 규칙\n"
                "- 오디오에 사람의 말이 없거나 알아들을 수 없으면 반드시 빈 문자열만 출력하세요.\n"
                "- 잡음, 배경 소음, 기계음만 있는 경우에도 빈 문자열만 출력하세요.\n"
                "- 오디오에 없는 내용을 절대 생성하지 마세요. 추측이나 보완 금지.\n"
                "- 실제로 들리는 말만 그대로 받아적으세요.\n"
                f"{dict_hint}",
            ],
        )
        text = response.text.strip()
        # 빈 결과 또는 일반적인 무음 응답 필터링
        if text in ("", "(무음)", "(silence)", "...", "없음", "빈 문자열"):
            return ""
        # 전사 결과가 비정상적으로 짧은 오디오에서 너무 긴 경우 환각 의심
        # WAV 헤더(44바이트) 제외 후 오디오 길이 추정 (16kHz, 16bit = 32000 bytes/sec)
        audio_data_size = max(len(wav_bytes) - 44, 0)
        audio_duration_sec = audio_data_size / 32000
        # 한국어 평균 발화 속도: ~4-5 음절/초, 1음절 ≈ 1.5자 → ~7자/초가 상한
        max_chars = max(int(audio_duration_sec * 10), 30)  # 여유 있게 10자/초, 최소 30자
        if len(text) > max_chars and audio_duration_sec < 5:
            # 5초 미만 오디오에서 비정상적으로 긴 텍스트 → 환각
            return ""
        return text

    def _transcribe_openai(self, wav_bytes: bytes) -> str:
        buf = io.BytesIO(wav_bytes)
        buf.name = "chunk.wav"
        result = self._client.audio.transcriptions.create(
            model="whisper-1",
            file=buf,
            language="ko",
        )
        return result.text.strip()

    def _transcribe_groq(self, wav_bytes: bytes) -> str:
        buf = io.BytesIO(wav_bytes)
        buf.name = "chunk.wav"
        result = self._client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=buf,
            language="ko",
        )
        return result.text.strip()

    def _transcribe_local_whisper(self, wav_bytes: bytes) -> str:
        """faster-whisper 로컬 모델로 전사. 오프라인, API 비용 0."""
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            audio_np = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

        transcribe_kwargs: dict = {
            "language": "ko",
            "beam_size": 5,
            "vad_filter": True,          # Silero VAD: 비음성 구간 잘라내기
            "vad_parameters": {"threshold": 0.5},  # VAD 민감도 (0=관대, 1=엄격)
            "condition_on_previous_text": False,   # 이전 청크 환각 전파 차단
        }
        if self.dictionary:
            transcribe_kwargs["initial_prompt"] = f"참고 단어: {', '.join(self.dictionary)}"

        segments, _ = self._model.transcribe(audio_np, **transcribe_kwargs)
        text = " ".join(s.text.strip() for s in segments)
        return text.strip()


# ---------------------------------------------------------------------------
# Business Context (수壽 thesoo + ACUREX 아큐렉스)
# ---------------------------------------------------------------------------
BUSINESS_CONTEXT = """
## 메디스트림 비즈니스 컨텍스트 (2개 브랜드 통합)

### 조직 구조
- 모회사: 메디스트림 (퇴계원 원외탕전실 운영)
- 브랜드 1: **수壽(thesoo)** — 한약 (경옥고, 공진단 등 프리미엄 보약)
- 브랜드 2: **ACUREX(아큐렉스)** — 약침 (한의계 최초 브랜드 약침)
- 공통: B2D 모델, 동일 원외탕전실, 멤버스/공동이용계약 인프라 공유

---

### [수壽] 브랜드
- 정의: 한의사가 만든 한의 브랜드. 12년차 한의사 페르소나
- 비전: 5천만 국민이 먹는 한약
- 캠페인: 이정재 "한약의 새로운 시대, 수壽" (25-26)
- 핵심가치: 신뢰/안전(hGMP), 전통+현대 융합, 진심, 프리미엄
- 톤: 느낌표 금지, 최상급/과장 금지, 데이터 기반, 품위 있는 어조

### [수壽] 제품
1. 프리미엄 한약: 공진단 5종(원방/사향/침향/녹용/총명), 경옥고 2종, 녹용한약, 우황청심원 2종, 자하거
2. 상비약: 콜드퀵 4종(감기), 까스퀵 4종(소화)
3. 2026 신규: 녹용활맥모과환(관절), 공진단벌크, 녹용십전대보탕, 쌍화탕, 생맥산, 당귀수산

---

### [ACUREX] 브랜드
- 정의: 한의계 최초의 브랜드 약침. '한의계 오스템' 전략
- 비전: 5,000만 국민이 "약침 하면 ACUREX"를 떠올리는 것
- 핵심가치: 압도적 품질(K-GMP 넘어선 설비), 시장 표준화, 전문가 교육, 동반 성장
- 톤: 전문적/자신감/교육적/명확. 모호한 표현 금지
- 주의: "주사" 표현 불가(의료법), "할인" 표현 지양(리베이트 위험), 약침 "녹이기" 안내 절대 금지

### [ACUREX] 제품
1. 브랜드 약침: 태반약침(갱년기/진통), 라인약침(지방분해), 무통약침(진통/항염)
2. 출시예정: 미백약침(6월), PN약침, NO약침
3. 콜라보: 자하거 수(=태반약침, 수壽 디자인), Lean 라인(=라인약침, 린다이어트 디자인)
4. Medistream Standard: 중성어혈, 황련해독, 죽염(자보 청구용)

### [ACUREX] KPI (11/19 기준)
- 멤버스 가입: 1,515개소 / 첫구매: 845개소 / 누적매출: 11.2억

### [ACUREX] 비즈니스 특이사항
- 조제의뢰 프로세스: 멤버스 가입 → 공동이용계약 → 사전처방(20일 소요, 단축 불가) → 조제의뢰
- 중앙 처방가 통제: 태반/라인 1회 2cc 3만원, 무통 2만원 (하한선)
- 할인규칙: 1-4회 정가, 5-9회 20%↓, 10회+ 30%↓

---

### 공통 비즈니스 모델
- B2D(Business to Doctor): 한의원에 공급 → 한의원이 환자에게 처방/판매
- 핵심 KPI: PU(구매 한의원 수), ARPPU(한의원당 매출), GMV
- 세일즈 세그먼트: Champion/Heavy/Regular/Light/Dormant/New 6단계
- 핵심 전략: Light→Regular 전환, Dormant 재활성화, 수壽↔ACUREX 크로스셀

### 마케팅 채널
- 카카오 비즈보드/플친 메시지, 카드뉴스, 숏폼, 이메일, Live 교육
- B2D 특성: 원장님 대상 교육 콘텐츠, 처방 가이드, VMD 키트, ACUREX 세션

### 경쟁 환경
- 수壽: 옥천당, 동의한방, 해밀 (원외탕전실) / 광동제약 (우황청심원)
- ACUREX: DCA 지방분해주사(양방), 산삼비만약침, 리포사약침 (타 원탕)
- 공통 차별화: 디자인, 설비(자동이물검사기), HPLC 분석, 보건복지부 인증
"""


# ---------------------------------------------------------------------------
# AI Assistant (Gemini)
# ---------------------------------------------------------------------------
class AIAssistant:
    """Gemini-based meeting minutes & idea generation with business context."""

    def __init__(self, context: str = ""):
        self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self._model = "gemini-2.5-flash"
        self.context = context or BUSINESS_CONTEXT

    def generate_minutes(self, transcript: str, title: str = "") -> str:
        prompt = f"""전문 회의록 작성자로서 아래 녹취록을 구조화된 회의록으로 작성하세요.
녹취록 내용만 정리한다. 녹취록에 없는 내용을 추가하거나 해석하지 않는다.

## 회의 정보
- 제목: {title or '(미지정)'}
- 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}
- 조직: 수壽(thesoo) B2D 마케팅팀

## 녹취록
{transcript}

## 작성 형식 (반드시 이 구조를 따를 것)

### 회의 요약
- 주요 안건 1줄 요약

### 논의 사항
1. [안건명]: 핵심 내용 2-3문장

### 결정 사항
- 구체적 결정 내용 나열

### Action Items
| 항목 | 담당(추정) | 기한(추정) |
|------|-----------|-----------|

### 후속 논의 필요 사항
- 미결 이슈

## 용어 참조 (제품명/용어 정확성 검증용)
{self.context}

## 규칙
- 두괄식, 짧은 문장
- 추상적 표현 금지
- 녹취록에 없는 내용 추가 금지. 위 비즈니스 컨텍스트는 용어 정확성 검증에만 사용
- 발화 내용에서 핵심만 추출하여 정리
- 수壽 제품명/용어가 나오면 정확한 명칭 사용 (예: 사향공진단 수, 콜드퀵 S)
- B2D 맥락에서 '고객'은 한의원 원장님, '최종소비자'는 환자/일반인으로 구분"""
        response = self._client.models.generate_content(
            model=self._model, contents=prompt
        )
        return response.text

    def generate_mid_summary(self, transcript: str, elapsed: str = "") -> str:
        prompt = f"""회의 진행 중 중간 정리를 담당하는 AI입니다.
지금까지의 논의를 간결하게 정리하여 참석자들이 흐름을 놓치지 않도록 돕습니다.
녹취록에 있는 내용만 정리한다. 녹취록에 없는 내용을 추가하거나 해석하지 않는다.

## 경과 시간: {elapsed or '미상'}

## 지금까지의 녹취록
{transcript}

## 출력 형식 (반드시 이 구조를 따를 것)

### 지금까지 논의한 내용
1. [안건/주제]: 핵심 내용 1-2문장
2. ...

### 합의된 사항
- 참석자 간 합의가 이루어진 내용 (없으면 "아직 없음")

### 아직 결론 안 난 사항
- 결론이 나지 않았거나 추가 논의가 필요한 이슈

### 다음으로 논의하면 좋을 주제
- 녹취록에서 언급됐지만 깊이 다루지 못한 주제 1-2개

## 용어 참조 (제품명/용어 정확성 검증용)
{BUSINESS_CONTEXT}

## 규칙
- 두괄식, 짧은 문장. 3줄 이상 연속 서술 금지
- 녹취록에 없는 내용 추가 금지. 위 비즈니스 컨텍스트는 용어 정확성 검증에만 사용
- 미사여구 금지
- 수壽/ACUREX 제품명 정확히 표기
- B2D 맥락에서 '고객'=한의원 원장님, '최종소비자'=환자"""
        response = self._client.models.generate_content(
            model=self._model, contents=prompt
        )
        return response.text

    def _build_idea_prompt(self, transcript: str, user_prompt: str = "") -> str:
        recent = transcript[-3000:] if len(transcript) > 3000 else transcript
        return f"""당신은 수壽(thesoo) 전략회의에 참석한 시니어 컨설턴트입니다.
회의 내용을 듣고 실행 가능한 아이디어를 3가지 관점에서 제안합니다.

## ★ 최우선 규칙: 녹취록이 아이디어의 유일한 근거다
- 아래 녹취록에서 **실제로 논의된 주제**만 아이디어의 출발점으로 삼을 것
- 비즈니스 컨텍스트는 아이디어를 검증/보강할 때만 참조한다. 컨텍스트에서 주제를 꺼내오지 마라
- 녹취록이 비즈니스 논의가 아닌 경우(잡담, 테스트, 일상 대화 등) 아래 형식으로 응답:
  → "현재 녹취록에 비즈니스 논의 내용이 부족합니다. 회의가 좀 더 진행된 후 다시 시도해주세요."

## 녹취록 (전체)
{transcript[:5000]}

## 최근 논의 (집중 분석 대상)
{recent}

{f"## 요청 방향: {user_prompt}" if user_prompt else ""}

## 비즈니스 컨텍스트 (검증/보강 전용 — 여기서 주제를 꺼내지 마라)
{self.context}

## 사고 프로세스 (반드시 순서대로)
0단계. 녹취록 검증: 녹취록에 구체적 비즈니스 논의(제품, 전략, 고객, 캠페인, KPI 등)가 있는가?
  - 없으면 → "비즈니스 논의 부족" 메시지만 출력하고 종료
  - 있으면 → 1단계로 진행
1단계. 맥락 파악: 녹취록에서 실제 논의된 주제를 정확히 1줄로 정의. 녹취록 원문을 인용할 것
2단계. 3관점 아이디어 도출 (각 관점에서 녹취록 주제에 직접 연결되는 아이디어만):
  - [사업전략] OKR 기여도, 수익 임팩트, ROI 관점
  - [세일즈] PU 확보, 원장님 전환/리텐션, 크로스셀 관점
  - [마케팅] 채널 전략, 콘텐츠, 캠페인 관점
3단계. 실행 가능성 필터: 현재 리소스와 일정 내 실행 가능한지 검증

## 가드레일 (반드시 준수)
- 녹취록에 나온 맥락과 무관한 아이디어 절대 금지. 녹취록에 언급되지 않은 제품/전략을 제안하지 마라
- B2D 비즈니스 모델에 부합해야 함 (한의원 원장님이 고객)
- 의료법/광고 규제 위반 소지 아이디어에 명시적 경고 표시
- 수壽: 느낌표/최상급/과장 표현 금지, 비교광고 금지
- ACUREX: "주사" 표현 불가, "할인" 표현 지양(리베이트 위험), 약침 "녹이기" 안내 절대 금지
- "좋습니다", "훌륭합니다" 같은 미사여구 금지
- 추상적 제안 금지 (예: "마케팅을 강화하세요" → 구체적 채널+메시지+타겟 명시)
- 수壽와 ACUREX 간 크로스셀 기회가 녹취록에 언급됐으면 적극 제안

## 출력 형식

### 현재 논의 주제
(녹취록에서 실제 논의된 주제 1줄 + 근거 원문 인용)

### 아이디어 (사업전략 관점)
1. **[아이디어명]**: 구체적 실행안 (기대효과: 정량적 추정)
2. ...

### 아이디어 (세일즈 관점)
1. **[아이디어명]**: 구체적 실행안 (기대효과: 정량적 추정)
2. ...

### 아이디어 (마케팅 관점)
1. **[아이디어명]**: 구체적 실행안 (기대효과: 정량적 추정)
2. ...

### 리스크 & 유의사항
- 규제/비용/실행 측면에서 주의할 점"""

    def generate_ideas(self, transcript: str, user_prompt: str = "") -> str:
        prompt = self._build_idea_prompt(transcript, user_prompt)
        response = self._client.models.generate_content(
            model=self._model, contents=prompt
        )
        return response.text

    def generate_ideas_stream(self, transcript: str, user_prompt: str = "") -> Generator:
        prompt = self._build_idea_prompt(transcript, user_prompt)
        for chunk in self._client.models.generate_content_stream(
            model=self._model, contents=prompt
        ):
            if chunk.text:
                yield chunk.text

    def ask_ai(self, transcript: str, question: str, chat_history: list[dict] | None = None) -> str:
        """회의에 참여 중인 AI 동료로서 자유 질문에 답변."""
        recent = transcript[-4000:] if len(transcript) > 4000 else transcript

        history_text = ""
        if chat_history:
            recent_chats = chat_history[-6:]  # 최근 3턴
            history_text = "\n## 이전 대화\n" + "\n".join(
                f"{'[질문]' if m['role'] == 'user' else '[답변]'} {m['content']}"
                for m in recent_chats
            )

        prompt = f"""당신은 이 회의에 함께 참석하고 있는 AI 동료입니다.
회의 내용을 처음부터 듣고 있었고, 질문을 받으면 녹취록에 기반하여 답변합니다.

## 역할
- 회의에 같이 앉아있는 똑똑한 동료. 격식 없이 자연스럽게 답변
- 녹취록에 있는 내용을 근거로 답변. 없는 내용을 지어내지 않음
- 질문이 아이디어를 요구하면 구체적이고 실행 가능한 제안을 함
- 질문이 정리를 요구하면 두괄식으로 핵심만 정리

## 녹취록 (전체)
{transcript[:6000]}

## 최근 논의 (집중)
{recent}
{history_text}

## 비즈니스 컨텍스트 (용어/맥락 참조용)
{self.context}

## 질문
{question}

## 규칙
- 짧은 문장. 서술형 장문 금지
- 미사여구 금지 ("좋은 질문입니다" 같은 표현 절대 금지)
- 질문에 바로 답변. 전제/배경 설명 없이 핵심부터
- 녹취록에 근거가 있으면 해당 발화를 인용
- 녹취록이 부족하면 솔직히 "아직 관련 논의가 없었다"고 답변
- 수壽/ACUREX 제품명 정확히 표기
- 의료법/광고 규제 위반 소지가 있으면 경고 표시"""
        response = self._client.models.generate_content(
            model=self._model, contents=prompt
        )
        return response.text

    def generate_sales_note(self, transcript: str, title: str = "") -> str:
        """세일즈 미팅 노트 생성."""
        prompt = f"""B2D 세일즈 미팅 노트를 작성하세요.
녹취록 내용만 정리한다. 녹취록에 없는 내용을 추가하지 않는다.

## 회의 정보
- 제목: {title or '(미지정)'}
- 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}

## 녹취록
{transcript}

## 출력 형식

### 고객(원장님) 정보
- 이름/한의원명 (언급된 경우)
- 현재 처방 현황
- 관심 제품/니즈

### 핵심 논의
1. [주제]: 내용 1-2문장

### 고객 반응/피드백
- 긍정적 반응
- 우려/거부 사항

### Next Action
| 항목 | 담당 | 기한 |
|------|------|------|

### 크로스셀/업셀 기회
- 수壽↔ACUREX 교차 제안 가능성

## 용어 참조
{self.context}

## 규칙
- 두괄식, 짧은 문장
- B2D 맥락: '고객'=한의원 원장님"""
        response = self._client.models.generate_content(
            model=self._model, contents=prompt
        )
        return response.text

    def generate_onepage(self, transcript: str, title: str = "") -> str:
        """한 페이지 요약 문서 생성."""
        prompt = f"""아래 녹취록을 한 페이지 분량의 요약 문서로 정리하세요.
슬랙이나 이메일로 공유하기 좋은 형태로 작성합니다.
녹취록 내용만 정리한다.

## 회의: {title or '(미지정)'} | {datetime.now().strftime('%Y-%m-%d %H:%M')}

## 녹취록
{transcript}

## 출력 형식

### 한줄 요약
(회의 전체를 한 문장으로)

### 주요 결정
- 결정 1
- 결정 2

### Action Items
- [ ] 항목 (담당자, 기한)

### 공유 사항
- 팀 전체가 알아야 할 내용

## 규칙
- 전체 분량 20줄 이내
- 두괄식
- 추상적 표현 금지"""
        response = self._client.models.generate_content(
            model=self._model, contents=prompt
        )
        return response.text


# ---------------------------------------------------------------------------
# Meeting Engine (Orchestrator)
# ---------------------------------------------------------------------------
class MeetingEngine:
    """Orchestrates recording, transcription, and AI analysis."""

    def __init__(self, stt_engine: str = "gemini", interval: int = 30,
                 vad_threshold: float = 0.003, audio_source: str = "local",
                 context: str = "", dictionary: list[str] | None = None):
        if audio_source == "browser":
            self.recorder = BrowserAudioReceiver()
        else:
            self.recorder = AudioRecorder()
        self.audio_source = audio_source
        self.transcriber = Transcriber(engine=stt_engine, dictionary=dictionary)
        self.assistant = AIAssistant(context=context)
        self.interval = interval
        self.vad_threshold = vad_threshold

        self._transcript_segments: list[dict] = []
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None
        self._start_time: Optional[datetime] = None
        self.is_active = False
        self.status = "대기 중"
        self._api_calls = 0
        self._error_log: list[str] = []
        self._autosave_path: Optional[str] = None
        self._pending_audio: Optional[np.ndarray] = None  # VAD 실패 시 보존용
        self._consecutive_vad_failures = 0  # 연속 VAD 실패 카운터
        self._max_vad_failures = 3  # 이 횟수 초과 시 강제 전사
        self._full_audio_chunks: list[np.ndarray] = []  # 후처리용 전체 녹음 누적
        self._last_processed_rms: float = 0.0  # 화자 전환 감지용 이전 청크 에너지

    def set_autosave_path(self, path: str):
        """녹취록 중간 자동저장 경로 설정. 전사 성공 시마다 append."""
        self._autosave_path = path

    def save_full_wav(self, path: str) -> bool:
        """전체 녹음을 WAV 파일로 저장. pyannote 후처리용."""
        with self._lock:
            chunks = list(self._full_audio_chunks)
        if not chunks:
            return False
        audio = np.concatenate(chunks)
        wav_bytes = AudioRecorder.to_wav_bytes(audio)
        with open(path, "wb") as f:
            f.write(wav_bytes)
        return True

    def start(self):
        self._start_time = datetime.now()
        self.is_active = True
        self.status = "녹음 중"
        self.recorder.start()
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def stop(self):
        self.is_active = False
        self.status = "처리 중..."
        self.recorder.stop()
        # Process remaining buffer
        self._process_chunk()
        self.status = "종료됨"

    def _worker(self):
        while self.is_active:
            time.sleep(self.interval)
            if not self.is_active:
                break
            self._process_chunk()

    def _process_chunk(self):
        try:
            chunk = self.recorder.get_chunk()

            # 후처리용 전체 녹음 누적 (VAD 여부와 무관하게 raw 오디오 저장)
            if chunk is not None:
                with self._lock:
                    self._full_audio_chunks.append(chunk.copy())

            if chunk is None and self._pending_audio is None:
                return

            # 이전 VAD 실패분과 새 청크 합산
            if chunk is not None and self._pending_audio is not None:
                chunk = np.concatenate([self._pending_audio, chunk])
                self._pending_audio = None
            elif chunk is None:
                chunk = self._pending_audio
                self._pending_audio = None

            rms = float(np.sqrt(np.mean(chunk ** 2)))
            duration = len(chunk) / 16000
            self._error_log.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] 청크 {duration:.1f}초, RMS={rms:.6f}, VAD임계={self.vad_threshold}"
            )

            vad_passed = self.recorder.has_speech(chunk, threshold=self.vad_threshold)

            if not vad_passed:
                self._consecutive_vad_failures += 1
                force = self._consecutive_vad_failures > self._max_vad_failures and duration >= 5.0
                self._error_log.append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] VAD 미통과 ({self._consecutive_vad_failures}연속)"
                    f"{' → 강제 전사 시도' if force else ''}"
                )
                if not force:
                    # VAD 실패: 버리지 않고 보존 (최대 120초분까지만, 메모리 보호)
                    max_samples = 16000 * 120
                    if len(chunk) < max_samples:
                        self._pending_audio = chunk
                        self._error_log.append(
                            f"[{datetime.now().strftime('%H:%M:%S')}] 다음 청크에 합산 예정 ({duration:.1f}초 보존)"
                        )
                    else:
                        self._error_log.append(
                            f"[{datetime.now().strftime('%H:%M:%S')}] 120초 초과 → 폐기"
                        )
                    return
                # force=True: VAD를 무시하고 전사 진행 (아래로 계속)

            # 화자 전환 감지: 침묵 이후 에너지 프로파일이 크게 변하면 마커 삽입
            had_silence = self._consecutive_vad_failures > 0
            self._consecutive_vad_failures = 0  # VAD 통과 또는 강제 전사 시 리셋
            self._pending_audio = None

            if had_silence and self._last_processed_rms > 0:
                energy_change = abs(rms - self._last_processed_rms) / max(self._last_processed_rms, 0.001)
                if energy_change > 0.5:  # 에너지 50% 이상 변화 → 화자 전환 추정
                    marker = {
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "text": "--- 화자 전환 ---",
                    }
                    with self._lock:
                        self._transcript_segments.append(marker)
                    self._autosave_segment(marker)

            # 오디오 품질 사전 검증: RMS가 극히 낮으면 전사 스킵 (API 절약 + 환각 방지)
            min_rms_for_stt = 0.002  # VAD 임계값(0.003)에 근접한 사실상 무음 판단선
            if rms < min_rms_for_stt:
                self._error_log.append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] RMS {rms:.6f} < {min_rms_for_stt} → 전사 스킵 (무음)"
                )
                return

            self.status = "전사 중..."
            wav_bytes = self.recorder.to_wav_bytes(chunk)
            text = self.transcriber.transcribe(wav_bytes)
            self._api_calls += 1

            # 환각(hallucination) 필터: 무음 구간에서 whisper가 반복 출력하는 패턴 제거
            # 부분 문자열 매칭: 패턴을 포함하는 텍스트 전체를 환각으로 처리
            _HALLUCINATION_PATTERNS = [
                "구독과 좋아요", "좋아요 구독", "mbc 뉴스", "자막 제공",
                "다음 시간에 만나요", "시청해 주셔서 감사합니다", "참고 단어",
                "한국어 회의 전사", "번역 자막", "자막 제작", "영상 시청",
                "구독 알림", "알림 설정", "다음 영상", "감사합니다 구독",
            ]
            if text:
                tl = text.strip().lower()
                for pattern in _HALLUCINATION_PATTERNS:
                    if pattern in tl:
                        text = ""
                        break

            if text and not text.startswith("[STT 오류"):
                segment = {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "text": text,
                }
                with self._lock:
                    self._transcript_segments.append(segment)
                # 중간 자동저장 (append)
                self._autosave_segment(segment)

            self._last_processed_rms = rms  # 화자 전환 감지를 위한 에너지 갱신
            self.status = "녹음 중"
        except Exception as e:
            err = f"[{datetime.now().strftime('%H:%M:%S')}] {str(e)[:100]}"
            self._error_log.append(err)
            self.status = "오류 발생 (녹음 계속 중)"

    def _autosave_segment(self, segment: dict):
        """전사 성공 시마다 파일에 append. 앱 크래시 시에도 직전까지 보존."""
        if not self._autosave_path:
            return
        try:
            line = f"[{segment['time']}] {segment['text']}\n"
            with open(self._autosave_path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass  # 저장 실패가 녹음을 멈추면 안 됨

    # -- Data access --
    def get_transcript_segments(self) -> list[dict]:
        with self._lock:
            return list(self._transcript_segments)

    def get_full_transcript(self) -> str:
        segments = self.get_transcript_segments()
        return "\n".join(f"[{s['time']}] {s['text']}" for s in segments)

    def get_volume_level(self) -> float:
        """현재 마이크 볼륨 레벨 (0.0~1.0)."""
        return self.recorder.current_rms if self.is_active else 0.0

    def get_elapsed_time(self) -> str:
        if not self._start_time:
            return "00:00:00"
        elapsed = datetime.now() - self._start_time
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def add_manual_note(self, note: str):
        """Add a manual text note to the transcript."""
        segment = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "text": f"[메모] {note}",
        }
        with self._lock:
            self._transcript_segments.append(segment)
        self._autosave_segment(segment)

    # -- AI actions --
    def generate_minutes(self, title: str = "") -> str:
        transcript = self.get_full_transcript()
        if not transcript:
            return "녹취록이 비어있습니다."
        self._api_calls += 1
        return self.assistant.generate_minutes(transcript, title)

    def generate_mid_summary(self) -> str:
        transcript = self.get_full_transcript()
        if not transcript:
            return "아직 녹취 내용이 없습니다."
        self._api_calls += 1
        return self.assistant.generate_mid_summary(transcript, self.get_elapsed_time())

    def generate_ideas(self, user_prompt: str = "") -> str:
        transcript = self.get_full_transcript()
        if not transcript:
            return "아직 녹취 내용이 없습니다. 회의를 시작하고 잠시 후 다시 시도하세요."
        self._api_calls += 1
        return self.assistant.generate_ideas(transcript, user_prompt)

    def generate_ideas_stream(self, user_prompt: str = "") -> Generator:
        transcript = self.get_full_transcript()
        if not transcript:
            yield "아직 녹취 내용이 없습니다."
            return
        self._api_calls += 1
        yield from self.assistant.generate_ideas_stream(transcript, user_prompt)

    def ask_ai(self, question: str, chat_history: list[dict] | None = None) -> str:
        """AI 동료에게 자유 질문. 녹취록 기반 답변."""
        transcript = self.get_full_transcript()
        if not transcript:
            return "아직 녹취 내용이 없습니다. 회의가 진행된 후 질문해주세요."
        self._api_calls += 1
        return self.assistant.ask_ai(transcript, question, chat_history)

    def generate_sales_note(self, title: str = "") -> str:
        transcript = self.get_full_transcript()
        if not transcript:
            return "녹취록이 비어있습니다."
        self._api_calls += 1
        return self.assistant.generate_sales_note(transcript, title)

    def generate_onepage(self, title: str = "") -> str:
        transcript = self.get_full_transcript()
        if not transcript:
            return "녹취록이 비어있습니다."
        self._api_calls += 1
        return self.assistant.generate_onepage(transcript, title)

    def set_context(self, context: str):
        """회의 맥락 업데이트."""
        self.assistant.context = context

    def set_dictionary(self, words: list[str]):
        """전문용어 단어장 업데이트."""
        self.transcriber.dictionary = words
