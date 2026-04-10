import { useEffect } from 'react'

interface ShortcutHandlers {
  onToggleRecording: () => void
  onFocusSearch: () => void
  onNewNote: () => void
}

export function useKeyboardShortcuts(
  handlers: ShortcutHandlers,
  isRecording: boolean,
  searchInputRef: React.RefObject<HTMLInputElement | null>,
) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement).isContentEditable

      // Space: 녹음 시작/중지 (입력 포커스 없을 때만)
      if (e.code === 'Space' && !isInput && !e.ctrlKey && !e.metaKey) {
        e.preventDefault()
        handlers.onToggleRecording()
        return
      }

      // Cmd+K / Ctrl+K: 검색 포커스
      if (e.code === 'KeyK' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        searchInputRef.current?.focus()
        return
      }

      // Cmd+N / Ctrl+N: 새 노트
      if (e.code === 'KeyN' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        handlers.onNewNote()
        return
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handlers, isRecording, searchInputRef])
}
