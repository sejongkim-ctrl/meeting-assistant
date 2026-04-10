import type { Folder, Note, RecordingStatus, DocTemplate, TranscriptSegment, RawSegment, ChatMsg, NoteSearchResult } from '../types'

const BASE = '/api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

// Folders
export const getFolders = () => req<Folder[]>('/folders')
export const createFolder = (name: string) =>
  req<Folder>('/folders', { method: 'POST', body: JSON.stringify({ name }) })

// Notes
export const getNotes = (folderId?: number) =>
  req<Note[]>('/notes' + (folderId != null ? `?folder_id=${folderId}` : ''))
export const getNote = (id: number) => req<Note>(`/notes/${id}`)
export const createNote = (title: string, folder_id?: number) =>
  req<Note>('/notes', { method: 'POST', body: JSON.stringify({ title, folder_id }) })
export const updateNote = (
  id: number,
  data: Partial<Pick<Note, 'title' | 'summary' | 'transcript' | 'diarized_script' | 'wav_path' | 'generated_docs'>>
) => req<Note>(`/notes/${id}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteNote = (id: number) =>
  req<{ ok: boolean }>(`/notes/${id}`, { method: 'DELETE' })

// Recording
export const startRecording = (noteId: number) =>
  req<{ ok: boolean }>('/recording/start', { method: 'POST', body: JSON.stringify({ note_id: noteId }) })
export const stopRecording = () =>
  req<{ wav_path: string | null; transcript: RawSegment[]; duration: string }>('/recording/stop', { method: 'POST' })
export const getRecordingStatus = () => req<RecordingStatus>('/recording/status')

// Post-process (diarization)
export const runPostprocess = (noteId: number) =>
  req<{ script: TranscriptSegment[]; speaker_mapping: Record<string, string> }>(
    `/postprocess/${noteId}`,
    { method: 'POST' }
  )

// Generate document
export const generateDoc = (noteId: number, template: DocTemplate) =>
  req<{ content: string }>('/generate', {
    method: 'POST',
    body: JSON.stringify({ note_id: noteId, template }),
  })

// Chat Q&A about a note
export const chatWithNote = (noteId: number, messages: ChatMsg[]) =>
  req<{ content: string }>('/chat', {
    method: 'POST',
    body: JSON.stringify({ note_id: noteId, messages }),
  })

// Search notes
export const searchNotes = (q: string) =>
  req<NoteSearchResult[]>(`/notes/search?q=${encodeURIComponent(q)}`)

// Share note → returns { share_token: string }
export const shareNote = (id: number) =>
  req<{ share_token: string }>(`/notes/${id}/share`, { method: 'POST' })

// Unshare note
export const unshareNote = (id: number) =>
  fetch(`/api/notes/${id}/share`, { method: 'DELETE' }).then(() => {})

// Get shared note by token
export const getSharedNote = (token: string) =>
  req<Note>(`/shared/${token}`)
