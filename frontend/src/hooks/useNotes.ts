import { useState, useEffect, useCallback } from 'react'
import { getFolders, getNotes, createNote } from '../api/client'
import type { Folder, Note } from '../types'

export function useNotes() {
  const [folders, setFolders] = useState<Folder[]>([])
  const [notes, setNotes] = useState<Note[]>([])
  const [selectedFolderId, setSelectedFolderId] = useState<number | undefined>()
  const [selectedNoteId, setSelectedNoteId] = useState<number | null>(null)

  const loadFolders = useCallback(async () => {
    const data = await getFolders()
    setFolders(data)
  }, [])

  const loadNotes = useCallback(async (folderId?: number) => {
    const data = await getNotes(folderId)
    setNotes(data)
  }, [])

  useEffect(() => {
    loadFolders()
    loadNotes()
  }, [loadFolders, loadNotes])

  const selectFolder = (id?: number) => {
    setSelectedFolderId(id)
    loadNotes(id)
  }

  const removeNote = useCallback((id: number) => {
    setNotes((prev) => prev.filter((n) => n.id !== id))
  }, [])

  const addNote = async (title = '새 노트') => {
    // 이미 로드된 notes state로 중복 체크 — API 재호출 불필요
    const titles = new Set(notes.map((n) => n.title))
    let finalTitle = title
    let i = 2
    while (titles.has(finalTitle)) {
      finalTitle = `${title}(${i++})`
    }
    const note = await createNote(finalTitle, selectedFolderId)
    setNotes((prev) => [note, ...prev])
    setSelectedNoteId(note.id)
    return note
  }

  const selectedNote = notes.find((n) => n.id === selectedNoteId) ?? null

  return {
    folders,
    notes,
    selectedFolderId,
    selectedNoteId,
    selectedNote,
    selectFolder,
    selectNote: setSelectedNoteId,
    addNote,
    removeNote,
    refreshNotes: () => loadNotes(selectedFolderId),
  }
}
