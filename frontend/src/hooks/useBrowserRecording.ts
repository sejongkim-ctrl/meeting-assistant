import { useState, useCallback, useRef, useEffect } from 'react'

const SAMPLE_RATE = 16000

function float32ToInt16(float32: Float32Array): ArrayBuffer {
  const buf = new ArrayBuffer(float32.length * 2)
  const view = new DataView(buf)
  for (let i = 0; i < float32.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32[i]))
    view.setInt16(i * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
  }
  return buf
}

export function useBrowserRecording(noteId: number | null) {
  const [isRecording, setIsRecording] = useState(false)
  const [duration, setDuration] = useState(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const isRecordingRef = useRef(false)
  const recordingNoteIdRef = useRef<number | null>(null)

  const stop = useCallback(async () => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    setIsRecording(false)
    isRecordingRef.current = false

    // Tear down audio pipeline
    processorRef.current?.disconnect()
    processorRef.current = null
    audioCtxRef.current?.close()
    audioCtxRef.current = null
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null

    // Close audio WebSocket — triggers backend recording_stopped broadcast
    wsRef.current?.close()
    wsRef.current = null
  }, [])

  // Auto-stop if the selected note changes while recording
  useEffect(() => {
    if (isRecordingRef.current) stop()
  }, [noteId]) // eslint-disable-line react-hooks/exhaustive-deps

  const start = useCallback(async (noteIdOverride?: number) => {
    const effectiveNoteId = noteIdOverride ?? noteId
    if (!effectiveNoteId) return
    recordingNoteIdRef.current = effectiveNoteId

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      alert('마이크 접근 권한이 필요합니다. 브라우저 설정에서 허용해 주세요.')
      return
    }
    streamRef.current = stream

    // AudioContext at 16kHz avoids resampling on the backend
    const audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE })
    audioCtxRef.current = audioCtx

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${protocol}://${window.location.host}/ws/audio`)
    wsRef.current = ws

    // Wait for WebSocket to open before streaming
    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve()
      ws.onerror = () => reject(new Error('WebSocket 연결 실패'))
    })

    const source = audioCtx.createMediaStreamSource(stream)
    // ScriptProcessorNode: 4096-frame buffer, 1 input channel, 1 output channel
    const processor = audioCtx.createScriptProcessor(4096, 1, 1)
    processorRef.current = processor

    processor.onaudioprocess = (e) => {
      if (!isRecordingRef.current || ws.readyState !== WebSocket.OPEN) return
      const int16 = float32ToInt16(e.inputBuffer.getChannelData(0))
      ws.send(int16)
    }

    source.connect(processor)
    processor.connect(audioCtx.destination) // required to keep onaudioprocess firing

    setIsRecording(true)
    isRecordingRef.current = true
    setDuration(0)
    timerRef.current = setInterval(() => setDuration((d) => d + 1), 1000)
  }, [noteId])

  const fmt = (s: number) =>
    `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

  return { isRecording, duration, durationStr: fmt(duration), start, stop, recordingNoteIdRef }
}
