import { useState, useCallback, useRef, useEffect } from 'react'
import { startRecording, stopRecording } from '../api/client'

export function useRecording(noteId: number | null) {
  const [isRecording, setIsRecording] = useState(false)
  const [duration, setDuration] = useState(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const isRecordingRef = useRef(false)
  const recordingNoteIdRef = useRef<number | null>(null)

  const stop = useCallback(async () => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    setIsRecording(false)
    isRecordingRef.current = false
    const result = await stopRecording()
    return result
  }, [])

  // 노트가 바뀌면 진행 중인 녹음 자동 종료
  useEffect(() => {
    if (isRecordingRef.current) {
      stop()
    }
  }, [noteId]) // eslint-disable-line react-hooks/exhaustive-deps

  const start = useCallback(async () => {
    if (!noteId) return
    // 즉시 UI 반영 (Optimistic)
    recordingNoteIdRef.current = noteId  // 시작 노트 고정
    setIsRecording(true)
    isRecordingRef.current = true
    setDuration(0)
    timerRef.current = setInterval(() => setDuration((d) => d + 1), 1000)
    try {
      await startRecording(noteId)
    } catch (e) {
      // API 실패 시 롤백
      if (timerRef.current) clearInterval(timerRef.current)
      setIsRecording(false)
      isRecordingRef.current = false
    }
  }, [noteId])

  const fmt = (s: number) =>
    `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

  return { isRecording, duration, durationStr: fmt(duration), start, stop, recordingNoteIdRef }
}
