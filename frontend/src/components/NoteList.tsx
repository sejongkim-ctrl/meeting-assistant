import { useState, useRef, useEffect } from 'react'
import type { Folder, Note, NoteSearchResult } from '../types'
import { searchNotes, shareNote } from '../api/client'

interface Props {
  folders: Folder[]
  notes: Note[]
  selectedFolderId?: number
  selectedNoteId: number | null
  onSelectFolder: (id?: number) => void
  onSelectNote: (id: number) => void
  onAddNote: (title: string) => void
  onDeleteNote: (id: number) => void
  onShowToast: (msg: string, type?: 'success' | 'error' | 'info') => void
  searchInputRef: React.RefObject<HTMLInputElement | null>
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
  onShowToast,
  searchInputRef,
}: Props) {
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<NoteSearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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

  const handleSearchChange = (val: string) => {
    setSearchQuery(val)
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    if (!val.trim()) {
      setSearchResults(null)
      return
    }
    setSearching(true)
    searchTimerRef.current = setTimeout(async () => {
      try {
        const results = await searchNotes(val)
        setSearchResults(results)
      } catch {
        setSearchResults([])
      } finally {
        setSearching(false)
      }
    }, 300)
  }

  const handleShare = async (e: React.MouseEvent, noteId: number) => {
    e.stopPropagation()
    try {
      const res = await shareNote(noteId)
      const url = `${window.location.origin}/app/?share=${res.share_token}`
      await navigator.clipboard.writeText(url)
      onShowToast('공유 링크가 클립보드에 복사됐습니다', 'success')
    } catch {
      onShowToast('공유 링크 생성에 실패했습니다', 'error')
    }
  }

  return (
    <aside className="note-list">
      <div className="note-list-header">
        <span className="note-list-title">노트</span>
        <button className="icon-btn" onClick={handleAddStart} title="새 노트">＋</button>
      </div>

      <div className="search-bar">
        <span className="search-icon">🔍</span>
        <input
          ref={searchInputRef}
          className="search-input"
          type="text"
          placeholder="노트 검색..."
          value={searchQuery}
          onChange={(e) => handleSearchChange(e.target.value)}
        />
        {searchQuery && (
          <button className="search-clear" onClick={() => handleSearchChange('')}>✕</button>
        )}
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
        {searchResults !== null ? (
          <div className="search-results">
            {searching && <p className="empty-hint">검색 중...</p>}
            {!searching && searchResults.length === 0 && (
              <p className="empty-hint">검색 결과가 없습니다.</p>
            )}
            {searchResults.map((r) => (
              <div
                key={r.id}
                className={`note-item ${r.id === selectedNoteId ? 'active' : ''}`}
                onClick={() => onSelectNote(r.id)}
              >
                <span className="note-item-title">{r.title}</span>
                {r.snippet && <p className="search-snippet">{r.snippet}</p>}
              </div>
            ))}
          </div>
        ) : (
          <>
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
                  className="note-share-btn"
                  title="공유 링크 복사"
                  onClick={(e) => handleShare(e, n.id)}
                >
                  🔗
                </button>
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
          </>
        )}
      </div>
    </aside>
  )
}
