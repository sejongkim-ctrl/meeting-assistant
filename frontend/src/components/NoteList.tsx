import { useState, useRef, useEffect } from 'react'
import type { Folder, Note } from '../types'

interface Props {
  folders: Folder[]
  notes: Note[]
  selectedFolderId?: number
  selectedNoteId: number | null
  onSelectFolder: (id?: number) => void
  onSelectNote: (id: number) => void
  onAddNote: (title: string) => void
  onDeleteNote: (id: number) => void
}

export default function NoteList({
  folders,
  notes,
  selectedFolderId,
  selectedNoteId,
  onSelectFolder,
  onSelectNote,
  onAddNote,
  onDeleteNote,
}: Props) {
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (adding) {
      inputRef.current?.focus()
    }
  }, [adding])

  const handleAddStart = () => {
    const now = new Date()
    setDraft(`회의 ${now.toLocaleDateString('ko-KR', { month: 'numeric', day: 'numeric' })}`)
    setAdding(true)
  }

  const handleAddConfirm = () => {
    const title = draft.trim()
    if (title) onAddNote(title)
    setAdding(false)
    setDraft('')
  }

  const handleAddCancel = () => {
    setAdding(false)
    setDraft('')
  }

  return (
    <aside className="note-list">
      <div className="note-list-header">
        <span className="note-list-title">노트</span>
        <button className="icon-btn" onClick={handleAddStart} title="새 노트">＋</button>
      </div>

      <div className="folder-section">
        <button
          className={`folder-item ${selectedFolderId == null ? 'active' : ''}`}
          onClick={() => onSelectFolder(undefined)}
        >
          📁 전체
        </button>
        {folders.map((f) => (
          <button
            key={f.id}
            className={`folder-item ${selectedFolderId === f.id ? 'active' : ''}`}
            onClick={() => onSelectFolder(f.id)}
          >
            📁 {f.name}
          </button>
        ))}
      </div>

      <div className="note-items">
        {adding && (
          <div className="note-add-row">
            <input
              ref={inputRef}
              className="note-add-input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAddConfirm()
                if (e.key === 'Escape') handleAddCancel()
              }}
              placeholder="노트 제목"
            />
            <button className="note-add-ok" onClick={handleAddConfirm}>✓</button>
            <button className="note-add-cancel" onClick={handleAddCancel}>✕</button>
          </div>
        )}

        {notes.length === 0 && !adding && (
          <p className="empty-hint">+ 버튼으로 노트를 추가하세요.</p>
        )}

        {notes.map((n) => (
          <div
            key={n.id}
            className={`note-item ${n.id === selectedNoteId ? 'active' : ''}`}
            onClick={() => onSelectNote(n.id)}
          >
            <span className="note-item-title">{n.title}</span>
            <div className="note-item-meta">
              <span className="note-item-date">
                {new Date(n.updated_at).toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' })}
              </span>
              {n.summary && <span className="note-summary-badge" title="요약 있음">●</span>}
              {(n.transcript?.length ?? 0) > 0 && !n.summary && (
                <span className="note-transcript-badge" title="전사 있음">○</span>
              )}
            </div>
            <button
              className="note-delete-btn"
              title="노트 삭제"
              onClick={(e) => {
                e.stopPropagation()
                if (confirm(`"${n.title}" 노트를 삭제할까요?`)) onDeleteNote(n.id)
              }}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </aside>
  )
}
