import { useCallback, useEffect, useRef, useState } from 'react'
import NoteList from './components/NoteList'
import MainPanel from './components/MainPanel'
import ChatPanel from './components/ChatPanel'
import BottomBar from './components/BottomBar'
import { useNotes } from './hooks/useNotes'
import { useBrowserRecording } from './hooks/useBrowserRecording'
import { useWebSocket } from './hooks/useWebSocket'
import { updateNote, deleteNote, generateDoc } from './api/client'
import type { WsMessage } from './types'
import './index.css'

export default function App() {
  const {
    folders, notes, selectedFolderId, selectedNoteId, selectedNote,
    selectFolder, selectNote, addNote, removeNote, refreshNotes,
  } = useNotes()
  const { isRecording, durationStr, start, stop, recordingNoteIdRef } = useBrowserRecording(selectedNoteId)
  const [liveLines, setLiveLines] = useState<string[]>([])
  const liveRef = useRef<string[]>([])

  // Auto-summary state: note_id → loading/content
  const [summaryLoading, setSummaryLoading] = useState<number | null>(null)
  const [summaryReady, setSummaryReady] = useState<number | null>(null) // note_id when ready

  useEffect(() => {
    liveRef.current = []
    setLiveLines([])
  }, [selectedNoteId])

  const triggerAutoSummary = useCallback(async (noteId: number) => {
    setSummaryLoading(noteId)
    setSummaryReady(null)
    try {
      const res = await generateDoc(noteId, 'summary')
      if (res.content) {
        // Save summary to note
        await updateNote(noteId, {
          summary: res.content,
          generated_docs: { summary: res.content },
        })
        setSummaryReady(noteId)
        await refreshNotes()
      }
    } catch (e) {
      console.error('[auto-summary] failed:', e)
    } finally {
      setSummaryLoading(null)
    }
  }, [refreshNotes])

  const handleWsMessage = useCallback((msg: WsMessage) => {
    if (msg.type === 'transcript' && msg.text) {
      const line = msg.speaker ? `[${msg.speaker}] ${msg.text}` : msg.text
      liveRef.current = [...liveRef.current, line]
      setLiveLines([...liveRef.current])
    } else if (msg.type === 'recording_stopped' && msg.data) {
      const noteId = recordingNoteIdRef.current
      if (noteId && msg.data.transcript.length > 0) {
        updateNote(noteId, {
          transcript: msg.data.transcript,
          wav_path: msg.data.wav_path ?? undefined,
        }).then(() => {
          refreshNotes()
          // Auto-generate summary after saving transcript
          triggerAutoSummary(noteId)
        })
      }
    }
  }, [recordingNoteIdRef, refreshNotes, triggerAutoSummary])

  useWebSocket(handleWsMessage)

  const handleAddNote = useCallback(async (title: string) => {
    await addNote(title)
  }, [addNote])

  const handleStart = useCallback(async () => {
    // Auto-create note if none selected
    let noteId = selectedNoteId
    if (!noteId) {
      const now = new Date()
      const title = `회의 ${now.toLocaleDateString('ko-KR')} ${now.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}`
      const note = await addNote(title)
      noteId = note.id
      selectNote(note.id)
    }
    liveRef.current = []
    setLiveLines([])
    await start(noteId ?? undefined)  // pass noteId directly to avoid stale closure
  }, [selectedNoteId, addNote, selectNote, start])

  const handleDeleteNote = useCallback(async (id: number) => {
    removeNote(id)
    if (selectedNoteId === id) selectNote(null)
    await deleteNote(id)
  }, [removeNote, selectedNoteId, selectNote])

  const handleStop = useCallback(async () => {
    await stop()
  }, [stop])

  return (
    <div className="app-root">
      <NoteList
        folders={folders}
        notes={notes}
        selectedFolderId={selectedFolderId}
        selectedNoteId={selectedNoteId}
        onSelectFolder={selectFolder}
        onSelectNote={selectNote}
        onAddNote={handleAddNote}
        onDeleteNote={handleDeleteNote}
      />
      <MainPanel
        note={selectedNote}
        liveLines={liveLines}
        summaryLoading={summaryLoading === selectedNote?.id}
        summaryJustReady={summaryReady === selectedNote?.id}
        onRefresh={refreshNotes}
        onSummaryRead={() => setSummaryReady(null)}
      />
      <ChatPanel note={selectedNote} />
      <BottomBar
        isRecording={isRecording}
        durationStr={durationStr}
        noteTitle={selectedNote?.title ?? null}
        onStart={handleStart}
        onStop={handleStop}
      />
    </div>
  )
}
