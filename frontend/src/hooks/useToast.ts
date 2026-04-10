import { useState, useCallback, useRef } from 'react'

export type ToastType = 'success' | 'error' | 'info'

export interface Toast {
  id: number
  message: string
  type: ToastType
}

let _nextId = 1

export function useToast() {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())

  const hideToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    const timer = timersRef.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timersRef.current.delete(id)
    }
  }, [])

  const showToast = useCallback((message: string, type: ToastType = 'success') => {
    const id = _nextId++
    setToasts((prev) => [...prev, { id, message, type }])
    const timer = setTimeout(() => hideToast(id), 3000)
    timersRef.current.set(id, timer)
  }, [hideToast])

  return { toasts, showToast, hideToast }
}
