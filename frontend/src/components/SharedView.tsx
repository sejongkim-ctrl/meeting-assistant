import { useEffect, useState } from 'react'
import MainPanel from './MainPanel'
import type { Note } from '../types'

interface Props {
  token: string
}

export default function SharedView({ token }: Props) {
  const [note, setNote] = useState<Note | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(`/api/shared/${token}`)
      .then((r) => {
        if (!r.ok) throw new Error('공유된 노트를 찾을 수 없습니다.')
        return r.json()
      })
      .then((data) => setNote(data))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [token])

  if (loading) {
    return (
      <div className="shared-loading">
        <div className="summary-spinner" />
        <p>노트를 불러오는 중...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="shared-error">
        <div className="error-icon">🔒</div>
        <h2>노트를 찾을 수 없습니다</h2>
        <p>{error}</p>
      </div>
    )
  }

  return (
    <div className="shared-view">
      <div className="shared-header">
        <span className="shared-badge">공유된 노트 (읽기 전용)</span>
      </div>
      <MainPanel
        note={note}
        liveLines={[]}
        summaryLoading={false}
        summaryJustReady={false}
        onRefresh={() => {}}
        onSummaryRead={() => {}}
        readOnly
      />
    </div>
  )
}
