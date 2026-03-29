import type { Folder, Note } from '../types'

interface Props {
  folders: Folder[]
  notes: Note[]
  selectedFolderId?: number
  selectedNoteId: number | null
  onSelectFolder: (id?: number) => void
  onSelectNote: (id: number) => void
  onAddNote: () => void
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
  return (
    <aside className="note-list">
      <div className="note-list-header">
        <span className="note-list-title">노트</span>
        <button className="icon-btn" onClick={onAddNote} title="새 노트">＋</button>
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
        {notes.length === 0 && (
          <p className="empty-hint">노트가 없습니다.<br />+ 버튼으로 추가하세요.</p>
        )}
        {notes.map((n) => (
          <div
            key={n.id}
            className={`note-item ${n.id === selectedNoteId ? 'active' : ''}`}
            onClick={() => onSelectNote(n.id)}
          >
            <span className="note-item-title">{n.title}</span>
            <span className="note-item-date">
              {new Date(n.updated_at).toLocaleDateString('ko-KR')}
            </span>
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
