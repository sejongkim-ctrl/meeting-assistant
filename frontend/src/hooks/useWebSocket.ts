import { useEffect, useRef, useCallback, useState } from 'react'
import type { WsMessage } from '../types'

export function useWebSocket(onMessage: (msg: WsMessage) => void) {
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${protocol}://${window.location.host}/ws/transcription`)

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data) as WsMessage
        onMessage(msg)
      } catch {}
    }

    wsRef.current = ws
    return ws
  }, [onMessage])

  useEffect(() => {
    const ws = connect()
    return () => ws.close()
  }, [connect])

  return { connected }
}
