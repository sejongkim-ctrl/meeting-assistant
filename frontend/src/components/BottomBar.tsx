interface Props {
  isRecording: boolean
  durationStr: string
  noteTitle: string | null
  onStart: () => void
  onStop: () => void
}

export default function BottomBar({ isRecording, durationStr, noteTitle, onStart, onStop }: Props) {
  return (
    <footer className="bottom-bar">
      <span className="bottom-note-name">{noteTitle ?? '노트를 선택하세요'}</span>

      <div className="bottom-center">
        {isRecording ? (
          <button className="rec-btn recording" onClick={onStop}>
            <span className="rec-dot" /> 녹음 중 {durationStr}
          </button>
        ) : (
          <button className="rec-btn" onClick={onStart} disabled={!noteTitle}>
            ⏺ 녹음 시작
          </button>
        )}
      </div>

      <span className="bottom-hint">
        {isRecording ? '중지하려면 버튼을 누르세요' : !noteTitle ? '노트를 선택해야 녹음할 수 있습니다' : ''}
      </span>
    </footer>
  )
}
