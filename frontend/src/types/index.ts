export interface Folder {
  id: number
  name: string
  created_at: string
}

export interface RawSegment {
  text: string
  speaker?: string
  time: string
}

export interface Note {
  id: number
  folder_id: number | null
  title: string
  transcript: RawSegment[] | null
  diarized_script: TranscriptSegment[] | null
  summary: string | null
  wav_path: string | null
  generated_docs: Record<string, string> | null
  created_at: string
  updated_at: string
}

export interface TranscriptSegment {
  speaker: string
  speaker_label?: string
  start: number
  end: number
  text: string
  time: string
  color: string
}

export interface RecordingStatus {
  is_recording: boolean
  duration: number
  wav_path: string | null
}

export type DocTemplate =
  | 'summary'
  | 'minutes'
  | 'lecture'
  | 'ir'
  | 'agm'
  | 'sales'
  | 'interview'
  | 'free'

export interface WsMessage {
  type: 'transcript' | 'status' | 'error' | 'recording_stopped'
  text?: string
  speaker?: string
  time?: string
  message?: string
  data?: {
    segment_count: number
    transcript: RawSegment[]
    wav_path: string | null
  }
}
