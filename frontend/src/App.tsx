import { useCallback, useEffect, useRef, useState } from 'react'
import NoteList from './components/NoteList'
import MainPanel from './components/MainPanel'
import ChatPanel from './components/ChatPanel'
import BottomBar from './components/BottomBar'
import { useNotes } from './hooks/useNotes'
import { useBrowserRecording } from './hooks/useBrowserRecording'
import { useWebSocket } from './hooks/useWebSocket'
import { updateNote, deleteNote } from './api/client'
import type { WsMessage } from './types'
import './index.css'

export default function App() {
  const { folders, notes, selectedFolderId, selectedNoteId, selectedNote, selectFolder, selectNote, addNote, removeNote, refreshNotes } = useNotes()
  const { isRecording, durationStr, start, stop, recordingNoteIdRef } = useBrowserRecording(selectedNoteId)
  const [liveLines, setLiveLines] = useState<string[]>([])
  const liveRef = useRef<string[]>([])

  // 노트 전환 시 대화기록 초기화 (다른 노트의 스크립트가 보이지 않도록)
  useEffect(() => {
    liveRef.current = []
    setLiveLines([])
  }, [selectedNoteId])

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
        }).then(() => refreshNotes())
      }
    }
  }, [recordingNoteIdRef, refreshNotes])

  useWebSocket(handleWsMessage)

  const handleAddNote = async () => {
    const title = prompt('노트 제목을 입력하세요', '새 회의')
    if (!title) return
    await addNote(title)
  }

  const handleStart = async () => {
    liveRef.current = []
    setLiveLines([])
    await start()
  }

  const handleDeleteNote = async (id: number) => {
    removeNote(id)
    if (selectedNoteId === id) selectNote(null)
    await deleteNote(id)
  }

  const handleStop = async () => {
    // Stops the browser recording + closes audio WebSocket.
    // The transcript is saved when the backend broadcasts 'recording_stopped' via handleWsMessage.
    await stop()
  }

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
        onRefresh={refreshNotes}
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
