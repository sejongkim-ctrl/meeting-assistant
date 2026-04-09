"""
AI Meeting Assistant - Streamlit App
마이크 ON → 자동 녹취/회의록, 아이디어 즉시 생성
"""

import os
import queue
import threading
import numpy as np
import streamlit as st
from datetime import datetime
from pathlib import Path

# WebRTC (원격 브라우저 마이크 지원)
try:
    from streamlit_webrtc import webrtc_streamer, WebRtcMode
    import av as _av
    HAS_WEBRTC = True
except ImportError:
    HAS_WEBRTC = False


# ---------------------------------------------------------------------------
# WebRTC Audio Bridge
# ---------------------------------------------------------------------------
class _ReceiverRef:
    """WebRTC 콜백 → BrowserAudioReceiver 연결용 가변 컨테이너."""
    receiver = None
    frame_count = 0  # 디버그: 수신 프레임 수

# Streamlit rerun 시 globals() dict가 재사용됨.
# 매번 새 객체를 만들면 WebRTC 콜백 스레드가 receiver=None인 객체를 참조하게 됨.
if '_receiver_ref' not in globals() or not hasattr(_receiver_ref, 'receiver'):
    _receiver_ref = _ReceiverRef()


def _audio_frame_callback(frame):
    """WebRTC 오디오 프레임을 BrowserAudioReceiver로 전달."""
    _receiver_ref.frame_count += 1
    receiver = _receiver_ref.receiver
    if receiver is None:
        return frame
    try:
        raw = frame.to_ndarray()
        # 스테레오 → 모노 변환 (채널 평균)
        if raw.ndim == 2:
            raw = raw.mean(axis=0)
        audio = raw.flatten().astype(np.float32)
        # int16 → float32 정규화
        if np.abs(audio).max() > 1.0:
            audio = audio / 32768.0
        # 리샘플링 (48kHz → 16kHz 등)
        sr = frame.sample_rate
        if sr != 16000:
            if sr % 16000 == 0:
                audio = audio[:: sr // 16000]
            else:
                target_len = int(len(audio) * 16000 / sr)
                audio = np.interp(
                    np.linspace(0, len(audio) - 1, target_len),
                    np.arange(len(audio)), audio,
                ).astype(np.float32)
        receiver.push_audio(audio)
    except Exception as e:
        import sys
        print(f"[audio_callback] frame={_receiver_ref.frame_count} sr={frame.sample_rate} err={e}", file=sys.stderr)
    return frame


# ---------------------------------------------------------------------------
# Auto-save Utility
# ---------------------------------------------------------------------------
SAVE_BASE = Path.home() / "Downloads" / "ai 회의록"


def _get_meeting_dir(title: str = "", start_time: datetime | None = None) -> Path:
    """회의별 폴더 생성/반환. 세션 내 동일 폴더 재사용."""
    ts = (start_time or datetime.now()).strftime("%Y%m%d_%H%M")
    safe_title = title.strip().replace("/", "-").replace(":", "-") if title else ""
    folder_name = f"{ts}_{safe_title}" if safe_title else ts
    meeting_dir = SAVE_BASE / folder_name
    meeting_dir.mkdir(parents=True, exist_ok=True)
    return meeting_dir


def save_file(meeting_dir: Path, filename: str, content: str, ext: str = ".md") -> Path:
    """파일 저장. 동일 이름 존재 시 번호 증가 (_2, _3...)."""
    base = meeting_dir / f"{filename}{ext}"
    if not base.exists():
        base.write_text(content, encoding="utf-8")
        return base
    n = 2
    while True:
        path = meeting_dir / f"{filename}_{n}{ext}"
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            return path
        n += 1

st.set_page_config(
    page_title="AI 회의 어시스턴트",
    page_icon="🎙️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    .transcript-box {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 16px;
        font-family: 'Pretendard', sans-serif;
    }
    .status-recording {
        color: #e74c3c;
        font-weight: bold;
    }
    .status-idle {
        color: #7f8c8d;
    }
    div[data-testid="stMetric"] {
        background-color: #f0f2f6;
        padding: 12px;
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session State Init
# ---------------------------------------------------------------------------
# 화자 분리 후처리 결과 브리지 (백그라운드 스레드 → Streamlit)
if "_diarization_queue" not in st.session_state:
    st.session_state._diarization_queue = queue.Queue()

if "engine" not in st.session_state:
    st.session_state.engine = None
    st.session_state.is_recording = False
    st.session_state.ai_result = ""
    st.session_state.ai_result_type = ""
    st.session_state.ai_results_history = []  # [{type, content, time}]
    st.session_state.meeting_dir = None
    st.session_state.chat_history = []  # AI 동료 대화 히스토리
    st.session_state.diarization_status = "idle"   # idle|running|done|error
    st.session_state.diarization_script = []        # 화자별 전사 결과
    st.session_state.speaker_mapping = {}           # {SPEAKER_XX: 이름}
    st.session_state.diarization_error = ""

# 후처리 결과 드레인: 백그라운드 스레드가 완료되면 session_state 갱신
_q = st.session_state._diarization_queue
while not _q.empty():
    _status, _payload, _mapping = _q.get_nowait()
    st.session_state.diarization_status = _status
    if _status == "done":
        st.session_state.diarization_script = _payload
        st.session_state.speaker_mapping = _mapping
    else:
        st.session_state.diarization_error = _payload

# WebRTC 브라우저 마이크 연결 복원:
# Streamlit은 매 rerun마다 모듈 레벨 변수를 초기화하므로
# session_state에 보존된 engine.recorder를 _receiver_ref에 다시 연결해야 한다.
if (st.session_state.is_recording
        and st.session_state.engine is not None
        and getattr(st.session_state.engine, "audio_source", "local") == "browser"):
    _receiver_ref.receiver = st.session_state.engine.recorder


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("설정")

    stt_engine = st.selectbox(
        "STT 엔진",
        ["gemini", "local-whisper", "openai", "groq"],
        index=0,
        help="gemini: API 키 하나로 전사+AI 모두 처리\nlocal-whisper: 로컬 faster-whisper (오프라인, 무료, 최초 480MB 다운)\nopenai: Whisper API (가장 정확)\ngroq: Whisper-large-v3 (가장 빠름)",
    )

    interval = st.slider(
        "전사 간격 (초)", 5, 60, 15, 5,
        help="짧을수록 실시간에 가깝지만 API 호출이 증가합니다",
    )

    vad_sensitivity = st.select_slider(
        "마이크 감도",
        options=["높음 (조용한 환경)", "보통", "낮음 (시끄러운 환경)"],
        value="보통",
        help="높음: 작은 소리도 감지 / 낮음: 큰 소리만 감지",
    )
    _vad_map = {"높음 (조용한 환경)": 0.001, "보통": 0.003, "낮음 (시끄러운 환경)": 0.008}
    vad_threshold = _vad_map[vad_sensitivity]

    if HAS_WEBRTC:
        audio_source_label = st.radio(
            "오디오 입력",
            ["🌐 브라우저 마이크", "🖥️ 호스트 마이크 (서버 PC)"],
            index=0,
            help="회의 시작을 누른 사람의 마이크를 사용합니다",
        )
        use_browser_mic = "브라우저" in audio_source_label
    else:
        use_browser_mic = False

    meeting_title = st.text_input(
        "회의 제목",
        placeholder="예: 주간 마케팅 미팅",
    )

    with st.expander("회의 맥락 (AI 정확도 향상)"):
        meeting_context = st.text_area(
            "이 회의의 배경/주제/참석자를 입력하세요",
            placeholder="예: 3월 콜드퀵 프로모션 기획 회의. 참석: 마케팅팀 3명, 세일즈팀 2명",
            height=80,
            help="입력하면 AI가 맥락을 이해하고 더 정확한 전사/문서를 생성합니다. 비워두면 기본 수壽/ACUREX 컨텍스트를 사용합니다.",
            label_visibility="collapsed",
        )
        custom_dict_input = st.text_input(
            "전문용어 단어장",
            placeholder="예: 사향공진단, 콜드퀵S, PU, ARPPU",
            help="쉼표로 구분. STT가 이 단어를 우선 인식합니다.",
        )
        custom_dictionary = [w.strip() for w in custom_dict_input.split(",") if w.strip()] if custom_dict_input else []

        # 엔진 실행 중이면 실시간 반영
        if st.session_state.engine:
            if meeting_context:
                st.session_state.engine.set_context(meeting_context)
            if custom_dictionary:
                st.session_state.engine.set_dictionary(custom_dictionary)

    st.divider()

    # Stats
    if st.session_state.engine:
        engine = st.session_state.engine
        st.caption(f"API 호출: {engine._api_calls}회")
        st.caption(f"전사 구간: {len(engine.get_transcript_segments())}개")
        # 브라우저 마이크 디버그 정보
        if getattr(engine, "audio_source", "local") == "browser":
            receiver_ok = "✅ 연결됨" if _receiver_ref.receiver is not None else "❌ None"
            st.caption(f"WebRTC 수신기: {receiver_ok} / 프레임: {_receiver_ref.frame_count}개")
            st.caption(f"VAD 연속실패: {engine._consecutive_vad_failures}회")
            buf_size = 0
            if hasattr(engine.recorder, '_buffer'):
                with engine.recorder._lock:
                    buf_size = sum(len(b) for b in engine.recorder._buffer)
            pending = len(engine._pending_audio) if engine._pending_audio is not None else 0
            st.caption(f"버퍼: {buf_size/16000:.1f}초 / 보류: {pending/16000:.1f}초")
        if engine._error_log:
            with st.expander(f"오류 로그 ({len(engine._error_log)})"):
                for err in engine._error_log[-5:]:
                    st.caption(err)

    # 저장 경로 표시
    if st.session_state.meeting_dir:
        st.caption(f"📁 {st.session_state.meeting_dir.name}/")

    st.divider()

    # Export
    if st.session_state.engine:
        transcript = st.session_state.engine.get_full_transcript()
        if transcript:
            st.download_button(
                "📥 녹취록 다운로드",
                transcript,
                file_name=f"녹취록_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                mime="text/plain",
                use_container_width=True,
            )

    if st.session_state.get("ai_result"):
        type_map = {"minutes": "회의록", "mid_summary": "중간정리", "ideas": "아이디어"}
        rtype = type_map.get(st.session_state.ai_result_type, "결과")
        st.download_button(
            f"📥 {rtype} 다운로드",
            st.session_state.ai_result,
            file_name=f"{rtype}_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
            mime="text/markdown",
            use_container_width=True,
        )

    # 참석자 이름 관리 (화자 분리 완료 후 표시)
    if st.session_state.get("speaker_mapping"):
        st.divider()
        st.subheader("참석자 이름 수정")
        st.caption("화자 ID를 실제 이름으로 수정하면 전체 스크립트에 반영됩니다.")
        updated_mapping = dict(st.session_state.speaker_mapping)
        for sp_id, current_name in list(st.session_state.speaker_mapping.items()):
            new_name = st.text_input(
                sp_id,
                value=current_name,
                key=f"speaker_name_{sp_id}",
            )
            updated_mapping[sp_id] = new_name
        if st.button("이름 적용", use_container_width=True):
            st.session_state.speaker_mapping = updated_mapping
            st.rerun()


# ---------------------------------------------------------------------------
# Stop Confirmation Dialog
# ---------------------------------------------------------------------------
@st.dialog("회의를 종료하시겠습니까?")
def confirm_stop_dialog():
    engine = st.session_state.engine
    seg_count = len(engine.get_transcript_segments()) if engine else 0
    elapsed = engine.get_elapsed_time() if engine else "00:00:00"
    st.warning(f"경과 시간: {elapsed} / 전사 구간: {seg_count}개")
    st.caption("종료 후에도 녹취록과 AI 결과는 자동 저장 폴더에 보존됩니다.")
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("종료", type="primary", use_container_width=True):
            _receiver_ref.receiver = None
            st.session_state.engine.stop()
            st.session_state.is_recording = False
            if st.session_state.meeting_dir:
                live_file = st.session_state.meeting_dir / "녹취록_live.txt"
                final_file = st.session_state.meeting_dir / "녹취록.txt"
                if live_file.exists():
                    live_file.rename(final_file)
                else:
                    transcript = st.session_state.engine.get_full_transcript()
                    if transcript:
                        save_file(st.session_state.meeting_dir, "녹취록", transcript, ".txt")
                # 후처리용 전체 녹음 WAV 자동 저장
                wav_path = st.session_state.meeting_dir / "recording.wav"
                st.session_state.engine.save_full_wav(str(wav_path))
            st.rerun()
    with col_no:
        if st.button("취소", use_container_width=True):
            st.rerun()


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🎙️ AI 회의 어시스턴트")
st.caption("마이크를 켜면 회의록을 자동 정리하고, 아이디어가 막힐 때 즉시 제안합니다.")


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([1, 1, 2])

with col_ctrl1:
    if not st.session_state.is_recording:
        if st.button("🔴 회의 시작", type="primary", use_container_width=True):
            try:
                from meeting_engine import MeetingEngine
                _src = "browser" if use_browser_mic else "local"
                engine = MeetingEngine(
                    stt_engine=stt_engine, interval=interval,
                    vad_threshold=vad_threshold, audio_source=_src,
                    context=meeting_context if meeting_context else "",
                    dictionary=custom_dictionary if custom_dictionary else None,
                )
                meeting_dir = _get_meeting_dir(meeting_title, datetime.now())
                autosave_file = meeting_dir / "녹취록_live.txt"
                engine.set_autosave_path(str(autosave_file))
                engine.start()
                if _src == "browser":
                    _receiver_ref.receiver = engine.recorder
                st.session_state.engine = engine
                st.session_state.is_recording = True
                st.session_state.ai_result = ""
                st.session_state.ai_result_type = ""
                st.session_state.ai_results_history = []
                st.session_state.meeting_dir = meeting_dir
                st.rerun()
            except Exception as e:
                st.error(f"시작 실패: {e}")
    else:
        if st.button("⬛ 회의 종료", type="secondary", use_container_width=True):
            confirm_stop_dialog()

with col_ctrl2:
    @st.fragment(run_every=1 if st.session_state.is_recording else None)
    def show_timer():
        if not st.session_state.engine:
            return
        # 브라우저 마이크 모드: fragment 재실행마다 receiver 참조를 재연결.
        # 메인 스크립트 rerun과 무관하게 1초마다 유효한 참조를 보장한다.
        if (st.session_state.is_recording
                and getattr(st.session_state.engine, "audio_source", "local") == "browser"
                and _receiver_ref.receiver is None):
            _receiver_ref.receiver = st.session_state.engine.recorder
        elapsed = st.session_state.engine.get_elapsed_time()
        status = st.session_state.engine.status
        st.metric("경과 시간", elapsed)
        if st.session_state.is_recording:
            vol = st.session_state.engine.get_volume_level()
            vol_pct = int(vol * 100)
            if vol < 0.05:
                vol_color = "#e74c3c"  # 빨강: 소리 없음
                vol_label = "🔇 무음"
            elif vol < 0.3:
                vol_color = "#f39c12"  # 주황: 작은 소리
                vol_label = "🔈 소리 감지"
            else:
                vol_color = "#27ae60"  # 초록: 정상
                vol_label = "🔊 녹음 중"
            st.progress(vol_pct, text=vol_label)
            st.markdown(f'<span class="status-recording">● {status}</span>', unsafe_allow_html=True)
        else:
            st.markdown(f'<span class="status-idle">○ {status}</span>', unsafe_allow_html=True)

    show_timer()


# ---------------------------------------------------------------------------
# Browser Microphone (WebRTC)
# ---------------------------------------------------------------------------
if (st.session_state.is_recording
        and HAS_WEBRTC
        and getattr(st.session_state.engine, "audio_source", "local") == "browser"):
    webrtc_ctx = webrtc_streamer(
        key="meeting-audio",
        mode=WebRtcMode.SENDONLY,
        desired_playing_state=True,
        audio_frame_callback=_audio_frame_callback,
        rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
        media_stream_constraints={"audio": True, "video": False},
    )
    if webrtc_ctx.state.playing:
        st.success("🎙️ 마이크 연결됨 — 녹음 중")
    else:
        st.info("🎙️ 마이크 연결 중... 브라우저에서 권한을 허용해주세요.")


# ---------------------------------------------------------------------------
# Transcript Display (auto-refreshing fragment)
# ---------------------------------------------------------------------------
st.subheader("실시간 녹취록")


@st.fragment(run_every=5 if st.session_state.is_recording else None)
def show_transcript():
    if not st.session_state.engine:
        st.info("'회의 시작' 버튼을 누르면 녹음이 시작됩니다.")
        return

    segments = st.session_state.engine.get_transcript_segments()

    if not segments:
        if st.session_state.is_recording:
            st.info(f"녹음 중... 첫 전사까지 약 {interval}초 소요됩니다.")
        else:
            st.warning("녹취 내용이 없습니다.")
        return

    with st.container(height=350):
        for seg in segments:
            if seg["text"].startswith("[메모]"):
                st.markdown(f"📝 `{seg['time']}` _{seg['text']}_")
            elif seg["text"] == "--- 화자 전환 ---":
                st.markdown(
                    f"<div style='border-top:1px dashed #aaa; margin:6px 0; color:#999; font-size:11px; text-align:center;'>"
                    f"↕ 화자 전환 추정 ({seg['time']})</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(f"`{seg['time']}` {seg['text']}")


show_transcript()


# ---------------------------------------------------------------------------
# 화자 분리 후처리 (회의 종료 후)
# ---------------------------------------------------------------------------
_wav_path = (
    st.session_state.meeting_dir / "recording.wav"
    if st.session_state.meeting_dir
    else None
)
_has_wav = _wav_path is not None and _wav_path.exists()
_diar_status = st.session_state.get("diarization_status", "idle")

if _has_wav and not st.session_state.is_recording:
    st.divider()
    st.subheader("화자 분리 후처리")

    if _diar_status == "idle":
        col_diar1, col_diar2 = st.columns([2, 1])
        with col_diar1:
            hf_token_input = st.text_input(
                "HuggingFace 토큰",
                type="password",
                placeholder="hf_xxxx (pyannote 모델 접근용)",
                help="https://hf.co/settings/tokens 에서 발급. 최초 1회 모델 동의 필요.",
            )
        with col_diar2:
            st.write("")
            st.write("")
            if st.button("후처리 시작", type="primary", use_container_width=True):
                hf_token = hf_token_input or os.getenv("HUGGINGFACE_TOKEN") or ""
                wav_str = str(_wav_path)
                result_q = st.session_state._diarization_queue

                def _diar_worker(wav, tok, q):
                    try:
                        from diarization import run_postprocess
                        from speaker_naming import infer_speaker_names
                        script = run_postprocess(wav, hf_token=tok or None)
                        mapping = infer_speaker_names(script)
                        q.put(("done", script, mapping))
                    except Exception as exc:
                        q.put(("error", str(exc), {}))

                t = threading.Thread(
                    target=_diar_worker,
                    args=(wav_str, hf_token, result_q),
                    daemon=True,
                )
                t.start()
                st.session_state.diarization_status = "running"
                st.rerun()

    elif _diar_status == "running":
        st.info("후처리 중... 1시간 녹음 기준 3~8분 소요됩니다.")
        st.progress(0.0, text="pyannote 화자 분리 + faster-whisper 재전사 진행 중")

    elif _diar_status == "error":
        st.error(f"후처리 실패: {st.session_state.get('diarization_error', '')}")
        if st.button("다시 시도"):
            st.session_state.diarization_status = "idle"
            st.rerun()

    elif _diar_status == "done":
        script = st.session_state.diarization_script
        mapping = st.session_state.speaker_mapping

        st.success(f"화자 분리 완료 — {len(set(s['speaker'] for s in script))}명 감지, {len(script)}개 구간")

        # 화자별 색상 스크립트 표시
        with st.container(height=400):
            for seg in script:
                label = mapping.get(seg["speaker"], seg["speaker"])
                color = seg.get("color", "#7f8c8d")
                st.markdown(
                    f"<div style='margin:4px 0;'>"
                    f"<span style='background:{color};color:#fff;padding:2px 8px;"
                    f"border-radius:4px;font-size:12px;font-weight:bold;'>{label}</span>"
                    f"&nbsp;<span style='color:#999;font-size:11px;'>{seg.get('time','')}</span>"
                    f"<br>{seg['text']}</div>",
                    unsafe_allow_html=True,
                )

        # 화자 구분 녹취록 다운로드
        from speaker_naming import format_labeled_transcript
        labeled_txt = format_labeled_transcript(script, mapping)
        if st.session_state.meeting_dir:
            labeled_path = st.session_state.meeting_dir / "녹취록_화자분리.txt"
            labeled_path.write_text(labeled_txt, encoding="utf-8")

        st.download_button(
            "📥 화자 구분 녹취록 다운로드",
            labeled_txt,
            file_name=f"녹취록_화자분리_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            mime="text/plain",
            use_container_width=True,
        )


# ---------------------------------------------------------------------------
# Manual Note
# ---------------------------------------------------------------------------
if st.session_state.engine:
    with st.expander("✏️ 수동 메모 추가"):
        note = st.text_input("메모 입력", placeholder="회의 중 추가할 메모를 입력하세요", label_visibility="collapsed")
        if st.button("메모 추가") and note:
            st.session_state.engine.add_manual_note(note)
            st.rerun()


# ---------------------------------------------------------------------------
# AI Actions
# ---------------------------------------------------------------------------
TYPE_MAP = {"minutes": "회의록", "mid_summary": "중간정리", "ideas": "아이디어",
            "sales_note": "세일즈노트", "onepage": "한페이지요약", "chat": "AI대화"}
TYPE_ICON = {"minutes": "📋", "mid_summary": "📌", "ideas": "💡",
             "sales_note": "🤝", "onepage": "📄", "chat": "💬"}
TYPE_FILE = {"minutes": "회의록", "mid_summary": "중간정리", "ideas": "아이디어",
             "sales_note": "세일즈노트", "onepage": "한페이지요약", "chat": "AI대화"}


def _save_ai_result(result: str, rtype: str):
    """AI 결과를 session state + 히스토리 + 파일에 저장."""
    st.session_state.ai_result = result
    st.session_state.ai_result_type = rtype
    st.session_state.ai_results_history.append({
        "type": rtype,
        "content": result,
        "time": datetime.now().strftime("%H:%M:%S"),
    })
    if st.session_state.meeting_dir:
        saved = save_file(st.session_state.meeting_dir, TYPE_FILE[rtype], result)
        st.toast(f"저장됨: {saved.name}")


st.divider()

engine_ready = st.session_state.engine is not None

# 문서 생성 버튼 (1행: 기본 3종)
col_a, col_b, col_c = st.columns(3)

with col_a:
    if st.button(
        "📋 회의록 정리",
        use_container_width=True,
        disabled=not engine_ready,
        help="녹취 내용을 구조화된 회의록으로 정리합니다",
    ):
        with st.spinner("회의록 작성 중..."):
            result = st.session_state.engine.generate_minutes(meeting_title)
            _save_ai_result(result, "minutes")
            st.rerun()

with col_b:
    if st.button(
        "📌 중간 정리",
        use_container_width=True,
        disabled=not engine_ready,
        help="지금까지 논의 내용을 정리하고 미결 사항을 파악합니다",
    ):
        with st.spinner("중간 정리 중..."):
            result = st.session_state.engine.generate_mid_summary()
            _save_ai_result(result, "mid_summary")
            st.rerun()

with col_c:
    if st.button(
        "💡 아이디어 제안",
        use_container_width=True,
        type="primary" if engine_ready else "secondary",
        disabled=not engine_ready,
        help="회의 맥락을 파악하여 즉시 아이디어를 제안합니다",
    ):
        with st.spinner("아이디어 생성 중..."):
            result = st.session_state.engine.generate_ideas()
            _save_ai_result(result, "ideas")
            st.rerun()

# 문서 생성 버튼 (2행: 추가 템플릿)
col_d, col_e, col_f = st.columns(3)

with col_d:
    if st.button(
        "🤝 세일즈 노트",
        use_container_width=True,
        disabled=not engine_ready,
        help="원장님 미팅 내용을 세일즈 노트로 정리합니다",
    ):
        with st.spinner("세일즈 노트 작성 중..."):
            result = st.session_state.engine.generate_sales_note(meeting_title)
            _save_ai_result(result, "sales_note")
            st.rerun()

with col_e:
    if st.button(
        "📄 한페이지 요약",
        use_container_width=True,
        disabled=not engine_ready,
        help="슬랙/이메일 공유용 한 페이지 요약을 생성합니다",
    ):
        with st.spinner("한페이지 요약 작성 중..."):
            result = st.session_state.engine.generate_onepage(meeting_title)
            _save_ai_result(result, "onepage")
            st.rerun()

with col_f:
    if st.button(
        "🎯 맞춤 아이디어",
        use_container_width=True,
        disabled=not engine_ready,
        help="특정 방향으로 아이디어를 요청합니다",
    ):
        st.session_state._show_idea_input = True

if st.session_state.get("_show_idea_input") and engine_ready:
    idea_prompt = st.text_input(
        "어떤 방향의 아이디어가 필요한가요?",
        placeholder="예: 비용 절감 방안, 마케팅 채널 다각화, 고객 이탈 방지 등",
        key="idea_direction",
    )
    if st.button("생성") and idea_prompt:
        with st.spinner("맞춤 아이디어 생성 중..."):
            result = st.session_state.engine.generate_ideas(idea_prompt)
            _save_ai_result(result, "ideas")
            st.session_state._show_idea_input = False
            st.rerun()


# ---------------------------------------------------------------------------
# AI Result Display (탭 히스토리)
# ---------------------------------------------------------------------------
history = st.session_state.get("ai_results_history", [])
if history:
    st.divider()
    st.subheader("AI 결과")

    # 탭 라벨: "📋 회의록 (14:32)" 형식, 최신이 왼쪽
    reversed_history = list(reversed(history))
    tab_labels = [
        f"{TYPE_ICON.get(h['type'], '📄')} {TYPE_MAP.get(h['type'], '결과')} ({h['time']})"
        for h in reversed_history
    ]
    tabs = st.tabs(tab_labels)
    for tab, item in zip(tabs, reversed_history):
        with tab:
            st.markdown(item["content"])
elif st.session_state.get("ai_result"):
    # 히스토리 없이 단일 결과만 있는 경우 (하위 호환)
    st.divider()
    rtype = st.session_state.ai_result_type
    st.subheader(f"{TYPE_ICON.get(rtype, '📄')} {TYPE_MAP.get(rtype, '결과')}")
    st.markdown(st.session_state.ai_result)


# ---------------------------------------------------------------------------
# AI 동료 채팅 (회의에 함께 참석한 AI에게 자유 질문)
# ---------------------------------------------------------------------------
st.divider()
st.subheader("💬 AI 동료에게 질문하기")
st.caption("회의 내용을 듣고 있는 AI에게 자유롭게 질문하세요. 예: \"지금까지 내용 기준으로 너의 아이디어는 뭐야?\"")

# 대화 히스토리 표시
for msg in st.session_state.get("chat_history", []):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 질문 입력
if question := st.chat_input(
    placeholder="회의 내용에 대해 질문하세요...",
    disabled=not engine_ready,
):
    # 사용자 질문 저장 + 표시
    st.session_state.chat_history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # AI 답변 생성
    with st.chat_message("assistant"):
        with st.spinner("생각 중..."):
            answer = st.session_state.engine.ask_ai(
                question, st.session_state.chat_history
            )
        st.markdown(answer)

    # 답변 저장
    st.session_state.chat_history.append({"role": "assistant", "content": answer})

    # 파일 자동저장
    if st.session_state.meeting_dir:
        chat_log = "\n\n".join(
            f"{'[Q]' if m['role'] == 'user' else '[A]'} {m['content']}"
            for m in st.session_state.chat_history
        )
        save_file(st.session_state.meeting_dir, "AI대화", chat_log)
