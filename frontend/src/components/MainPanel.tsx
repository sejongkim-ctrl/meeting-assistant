import { useState, useEffect, useRef } from 'react'
import type { Note, TranscriptSegment, DocTemplate } from '../types'
import { runPostprocess, generateDoc, updateNote } from '../api/client'

interface Props {
  note: Note | null
  liveLines: string[]
  onRefresh: () => void
}

type Tab = 'live' | 'script' | 'doc'

const TEMPLATES: { key: DocTemplate; label: string }[] = [
  { key: 'summary', label: '한페이지 요약' },
  { key: 'minutes', label: '회의록' },
  { key: 'lecture', label: '강의노트' },
  { key: 'ir', label: 'IR·피칭' },
  { key: 'agm', label: '주주총회' },
  { key: 'sales', label: '세일즈노트' },
  { key: 'interview', label: '채용인터뷰' },
  { key: 'free', label: '자유형식' },
]

export default function MainPanel({ note, liveLines, onRefresh }: Props) {
  const [tab, setTab] = useState<Tab>('live')
  const [script, setScript] = useState<TranscriptSegment[]>([])
  const [docText, setDocText] = useState('')
  const [loading, setLoading] = useState(false)
  const [docError, setDocError] = useState('')
  const [generatingDoc, setGeneratingDoc] = useState(false)
  const [generatingLabel, setGeneratingLabel] = useState('')
  const [docProgress, setDocProgress] = useState(0)
  const progressTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [savedDocs, setSavedDocs] = useState<Record<string, string>>({})
  const [activeDocKey, setActiveDocKey] = useState<string | null>(null)

  // note 전환 시 저장된 문서 히스토리 로드
  useEffect(() => {
    setSavedDocs(note?.generated_docs ?? {})
    setActiveDocKey(null)
    setDocText('')
    setDocError('')
  }, [note?.id])

  // 타이핑 애니메이션 state
  const [typingCharCount, setTypingCharCount] = useState(0)
  const typingIndexRef = useRef(-1)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (liveLines.length === 0) {
      typingIndexRef.current = -1
      setTypingCharCount(0)
      return
    }
    const lastIdx = liveLines.length - 1
    if (typingIndexRef.current === lastIdx) return // 이미 애니메이션 중
    typingIndexRef.current = lastIdx
    setTypingCharCount(0)
    if (timerRef.current) clearInterval(timerRef.current)
    const text = liveLines[lastIdx]
    let count = 0
    timerRef.current = setInterval(() => {
      count++
      setTypingCharCount(count)
      if (count >= text.length) {
        clearInterval(timerRef.current!)
        timerRef.current = null
      }
    }, 20)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [liveLines])

  const handlePostprocess = async () => {
    if (!note) return
    setLoading(true)
    try {
      const res = await runPostprocess(note.id)
      setScript(res.script)
      setTab('script')
      onRefresh()
    } finally {
      setLoading(false)
    }
  }

  const handleGenerate = async (tpl: DocTemplate) => {
    if (!note || generatingDoc) return
    const label = TEMPLATES.find((t) => t.key === tpl)?.label ?? tpl
    setGeneratingDoc(true)
    setGeneratingLabel(label)
    setDocError('')
    setDocProgress(0)
    if (progressTimerRef.current) clearInterval(progressTimerRef.current)
    progressTimerRef.current = setInterval(() => {
      setDocProgress((prev) => prev + (90 - prev) * 0.08)
    }, 300)
    try {
      const res = await generateDoc(note.id, tpl)
      setDocText(res.content)
      setActiveDocKey(tpl)
      setSavedDocs((prev) => {
        const next = { ...prev, [tpl]: res.content }
        updateNote(note.id, { generated_docs: next })
        return next
      })
      setTab('doc')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setDocError(msg)
      setTab('doc')
    } finally {
      if (progressTimerRef.current) { clearInterval(progressTimerRef.current); progressTimerRef.current = null }
      setDocProgress(100)
      setTimeout(() => {
        setGeneratingDoc(false)
        setGeneratingLabel('')
        setDocProgress(0)
      }, 600)
    }
  }

  const handleDownload = () => {
    const content = activeDocKey ? (savedDocs[activeDocKey] ?? '') : docText
    if (!content || !note) return
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${note.title}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (!note) {
    return (
      <main className="main-panel empty-panel">
        <p>왼쪽에서 노트를 선택하거나 새로 만드세요.</p>
      </main>
    )
  }

  return (
    <main className="main-panel">
      {generatingDoc && (
        <div className="doc-progress-toast">
          <span className="doc-progress-label">⏳ {generatingLabel} 생성 중...</span>
          <div className="doc-progress-bar"><div className="doc-progress-fill" style={{ width: `${docProgress}%` }} /></div>
        </div>
      )}
      <div className="main-header">
        <h2 className="note-title">{note.title}</h2>
        <div className="tab-bar">
          {(['live', 'script', 'doc'] as Tab[]).map((t) => (
            <button
              key={t}
              className={`tab-btn ${tab === t ? 'active' : ''}`}
              onClick={() => setTab(t)}
            >
              {t === 'live' ? '대화기록' : t === 'script' ? '화자 스크립트' : '맞춤문서'}
            </button>
          ))}
        </div>
      </div>

      <div className="tab-content">
        {tab === 'live' && (
          <div className="live-tab">
            {liveLines.length === 0 && !note.transcript?.length && (
              <p className="empty-hint">녹음을 시작하면 실시간 전사 내용이 여기 표시됩니다.</p>
            )}
            {liveLines.length > 0
              ? liveLines.map((line, i) => {
                  const isTyping = i === typingIndexRef.current
                  const display = isTyping ? line.slice(0, typingCharCount) : line
                  return (
                    <p key={i} className="live-line">
                      {display}
                      {isTyping && typingCharCount < line.length && (
                        <span className="typing-cursor">▌</span>
                      )}
                    </p>
                  )
                })
              : note.transcript?.map((seg, i) => (
                  <p key={i} className="live-line">
                    {seg.speaker ? `[${seg.speaker}] ` : ''}{seg.text}
                    <span className="seg-time" style={{ marginLeft: 8, fontSize: '0.75rem', opacity: 0.5 }}>{seg.time}</span>
                  </p>
                ))
            }
          </div>
        )}

        {tab === 'script' && (
          <div className="script-tab">
            <div className="script-actions">
              <button className="action-btn" onClick={handlePostprocess} disabled={loading}>
                {loading ? '분석 중...' : '화자 분리 후처리 실행'}
              </button>
            </div>
            {script.length === 0 && (
              <p className="empty-hint">후처리 실행 시 화자별 스크립트가 표시됩니다.</p>
            )}
            {script.map((seg, i) => (
              <div key={i} className="script-seg" style={{ borderLeftColor: seg.color }}>
                <span className="seg-speaker" style={{ color: seg.color }}>
                  {seg.speaker_label ?? seg.speaker}
                </span>
                <span className="seg-time">{seg.time}</span>
                <p className="seg-text">{seg.text}</p>
              </div>
            ))}
          </div>
        )}

        {tab === 'doc' && (() => {
          const visibleDoc = activeDocKey ? (savedDocs[activeDocKey] ?? '') : docText
          const historyKeys = TEMPLATES.filter((t) => savedDocs[t.key])
          return (
            <div className="doc-tab">
              <div className="template-grid">
                {TEMPLATES.map((tpl) => (
                  <button
                    key={tpl.key}
                    className="tpl-btn"
                    onClick={() => handleGenerate(tpl.key)}
                    disabled={generatingDoc}
                  >
                    {tpl.label}
                  </button>
                ))}
              </div>
              {historyKeys.length > 0 && (
                <div className="doc-history-bar">
                  <span className="doc-history-label">이전 생성</span>
                  {historyKeys.map((t) => (
                    <button
                      key={t.key}
                      className={`doc-history-chip ${activeDocKey === t.key ? 'active' : ''}`}
                      onClick={() => setActiveDocKey(t.key)}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              )}
              {docError && <p className="doc-error">{docError}</p>}
              {visibleDoc && (
                <div className="doc-output-wrap">
                  <button className="doc-download-btn" onClick={handleDownload}>⬇ MD 다운로드</button>
                  <div className="doc-output">{visibleDoc}</div>
                </div>
              )}
            </div>
          )
        })()}
      </div>
    </main>
  )
}
