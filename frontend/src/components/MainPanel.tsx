import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Note, TranscriptSegment, DocTemplate } from '../types'
import { runPostprocess, generateDoc, updateNote } from '../api/client'

interface Props {
  note: Note | null
  liveLines: string[]
  summaryLoading: boolean
  summaryJustReady: boolean
  onRefresh: () => void
  onSummaryRead: () => void
  readOnly?: boolean
}

type Tab = 'live' | 'summary' | 'script' | 'doc'

const TEMPLATES: { key: DocTemplate; label: string; icon: string }[] = [
  { key: 'summary', label: '한페이지 요약', icon: '📋' },
  { key: 'minutes', label: '회의록', icon: '📝' },
  { key: 'lecture', label: '강의노트', icon: '📚' },
  { key: 'ir', label: 'IR·피칭', icon: '📊' },
  { key: 'agm', label: '주주총회', icon: '🏛' },
  { key: 'sales', label: '세일즈노트', icon: '💼' },
  { key: 'interview', label: '채용인터뷰', icon: '👤' },
  { key: 'action_items' as DocTemplate, label: '액션 아이템', icon: '✅' },
  { key: 'free', label: '자유형식', icon: '✨' },
]

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button className="doc-action-btn" onClick={handleCopy}>
      {copied ? '✓ 복사됨' : '복사'}
    </button>
  )
}

function DownloadButton({ text, filename }: { text: string; filename: string }) {
  const handleDownload = () => {
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <button className="doc-action-btn" onClick={handleDownload}>
      ⬇ MD
    </button>
  )
}

export default function MainPanel({ note, liveLines, summaryLoading, summaryJustReady, onRefresh, onSummaryRead, readOnly }: Props) {
  const [tab, setTab] = useState<Tab>('live')
  const [script, setScript] = useState<TranscriptSegment[]>([])
  const [docText, setDocText] = useState('')
  const [docError, setDocError] = useState('')
  const [generatingDoc, setGeneratingDoc] = useState(false)
  const [generatingLabel, setGeneratingLabel] = useState('')
  const [docProgress, setDocProgress] = useState(0)
  const progressTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [savedDocs, setSavedDocs] = useState<Record<string, string>>({})
  const [activeDocKey, setActiveDocKey] = useState<string | null>(null)

  // Inline title editing
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const titleInputRef = useRef<HTMLInputElement>(null)

  // Typing animation
  const [typingCharCount, setTypingCharCount] = useState(0)
  const typingIndexRef = useRef(-1)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Auto-switch to summary tab when auto-summary is ready
  useEffect(() => {
    if (summaryJustReady) {
      setTab('summary')
      onSummaryRead()
    }
  }, [summaryJustReady, onSummaryRead])

  // Reset state when note changes
  useEffect(() => {
    setSavedDocs(note?.generated_docs ?? {})
    setActiveDocKey(null)
    setDocText('')
    setDocError('')
    setEditingTitle(false)
    // If note has a summary, pre-select summary tab
    if (note?.summary) {
      setTab('summary')
    } else if (note?.transcript?.length) {
      setTab('live')
    } else {
      setTab('live')
    }
  }, [note?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // Sync saved docs from note
  useEffect(() => {
    if (note?.generated_docs) {
      setSavedDocs(note.generated_docs)
    }
  }, [note?.generated_docs])

  // Typing animation for live transcript
  useEffect(() => {
    if (liveLines.length === 0) {
      typingIndexRef.current = -1
      setTypingCharCount(0)
      return
    }
    const lastIdx = liveLines.length - 1
    if (typingIndexRef.current === lastIdx) return
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

  const handleTitleEdit = () => {
    if (!note) return
    setTitleDraft(note.title)
    setEditingTitle(true)
    setTimeout(() => titleInputRef.current?.select(), 30)
  }

  const handleTitleSave = async () => {
    if (!note || !titleDraft.trim()) { setEditingTitle(false); return }
    setEditingTitle(false)
    if (titleDraft.trim() !== note.title) {
      await updateNote(note.id, { title: titleDraft.trim() })
      onRefresh()
    }
  }

  const handlePostprocess = async () => {
    if (!note) return
    try {
      const res = await runPostprocess(note.id)
      setScript(res.script)
      setTab('script')
      onRefresh()
    } catch (e) {
      alert('화자 분리 실패: ' + (e instanceof Error ? e.message : String(e)))
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

  if (!note) {
    return (
      <main className="main-panel empty-panel">
        <div className="welcome-state">
          <div className="welcome-icon">🎙️</div>
          <h2 className="welcome-title">AI 회의록 어시스턴트</h2>
          <div className="welcome-steps">
            <div className="welcome-step">
              <span className="step-num">1</span>
              <span>왼쪽 <strong>+</strong> 버튼으로 새 노트를 만드세요</span>
            </div>
            <div className="welcome-step">
              <span className="step-num">2</span>
              <span>하단 <strong>녹음 시작</strong>을 누르면 자동 전사됩니다</span>
            </div>
            <div className="welcome-step">
              <span className="step-num">3</span>
              <span>녹음 완료 후 <strong>AI 요약</strong>이 자동 생성됩니다</span>
            </div>
          </div>
          <p className="welcome-shortcuts">
            단축키: <kbd>Space</kbd> 녹음 · <kbd>⌘K</kbd> 검색 · <kbd>⌘N</kbd> 새 노트
          </p>
        </div>
      </main>
    )
  }

  const summaryContent = note.summary ?? savedDocs['summary'] ?? ''
  const visibleDoc = activeDocKey ? (savedDocs[activeDocKey] ?? '') : docText
  const historyKeys = TEMPLATES.filter((t) => savedDocs[t.key])

  return (
    <main className="main-panel">
      {generatingDoc && (
        <div className="doc-progress-toast">
          <span className="doc-progress-label">⏳ {generatingLabel} 생성 중...</span>
          <div className="doc-progress-bar">
            <div className="doc-progress-fill" style={{ width: `${docProgress}%` }} />
          </div>
        </div>
      )}

      <div className="main-header">
        <div className="title-row">
          {editingTitle ? (
            <input
              ref={titleInputRef}
              className="title-edit-input"
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              onBlur={handleTitleSave}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleTitleSave()
                if (e.key === 'Escape') setEditingTitle(false)
              }}
            />
          ) : (
            <h2 className="note-title" onClick={readOnly ? undefined : handleTitleEdit} title={readOnly ? undefined : '클릭하여 제목 편집'}>
              {note.title}
              <span className="title-edit-hint">✎</span>
            </h2>
          )}
          <span className="note-date">
            {new Date(note.updated_at).toLocaleDateString('ko-KR', {
              month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
            })}
          </span>
        </div>

        <div className="tab-bar">
          {([
            { key: 'live', label: '전사' },
            { key: 'summary', label: '요약', badge: summaryLoading ? '...' : undefined },
            { key: 'script', label: '화자' },
            { key: 'doc', label: '문서' },
          ] as { key: Tab; label: string; badge?: string }[]).map((t) => (
            <button
              key={t.key}
              className={`tab-btn ${tab === t.key ? 'active' : ''}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
              {t.badge && <span className="tab-badge">{t.badge}</span>}
            </button>
          ))}
        </div>
      </div>

      <div className="tab-content">
        {/* 전사 탭 */}
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
                    <span className="seg-time-inline">{seg.time}</span>
                    {seg.speaker ? <span className="seg-speaker-inline">{seg.speaker}</span> : null}
                    {seg.text}
                  </p>
                ))}
          </div>
        )}

        {/* 요약 탭 */}
        {tab === 'summary' && (
          <div className="summary-tab">
            {summaryLoading && (
              <div className="summary-loading">
                <div className="summary-spinner" />
                <p>AI가 회의 내용을 분석 중입니다...</p>
              </div>
            )}
            {!summaryLoading && !summaryContent && (
              <div className="summary-empty">
                <p className="empty-hint">
                  {note.transcript?.length
                    ? '아래 버튼을 눌러 요약을 생성하세요.'
                    : '녹음이 완료되면 자동으로 요약이 생성됩니다.'}
                </p>
                {note.transcript?.length ? (
                  <button className="action-btn" onClick={() => handleGenerate('summary')}>
                    요약 생성
                  </button>
                ) : null}
              </div>
            )}
            {!summaryLoading && summaryContent && (
              <div className="doc-output-wrap">
                <div className="doc-actions-row">
                  <CopyButton text={summaryContent} />
                  <DownloadButton text={summaryContent} filename={`${note.title}_요약.md`} />
                  <button className="doc-action-btn" onClick={() => handleGenerate('summary')} disabled={generatingDoc}>
                    재생성
                  </button>
                </div>
                <div className="doc-output markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{summaryContent}</ReactMarkdown>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 화자 스크립트 탭 */}
        {tab === 'script' && (
          <div className="script-tab">
            <div className="script-actions">
              {!readOnly && (
                <button className="action-btn" onClick={handlePostprocess}>
                  화자 분리 실행
                </button>
              )}
            </div>
            {(note.diarized_script?.length ?? 0) > 0 || script.length > 0 ? null : (
              <p className="empty-hint">화자 분리를 실행하면 발화자별 스크립트가 표시됩니다.</p>
            )}
            {(script.length > 0 ? script : (note.diarized_script ?? [])).map((seg, i) => (
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

        {/* 문서 탭 */}
        {tab === 'doc' && (
          <div className="doc-tab">
            <div className="template-grid">
              {TEMPLATES.map((tpl) => (
                <button
                  key={tpl.key}
                  className={`tpl-btn ${savedDocs[tpl.key] ? 'has-doc' : ''}`}
                  onClick={() => {
                    if (savedDocs[tpl.key] && activeDocKey !== tpl.key) {
                      setActiveDocKey(tpl.key)
                    } else {
                      handleGenerate(tpl.key)
                    }
                  }}
                  disabled={generatingDoc}
                >
                  <span className="tpl-icon">{tpl.icon}</span>
                  <span>{tpl.label}</span>
                  {savedDocs[tpl.key] && <span className="tpl-dot" />}
                </button>
              ))}
            </div>

            {historyKeys.length > 0 && (
              <div className="doc-history-bar">
                <span className="doc-history-label">생성된 문서</span>
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
                <div className="doc-actions-row">
                  <CopyButton text={visibleDoc} />
                  <DownloadButton
                    text={visibleDoc}
                    filename={`${note.title}_${TEMPLATES.find(t => t.key === activeDocKey)?.label ?? '문서'}.md`}
                  />
                </div>
                <div className="doc-output markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{visibleDoc}</ReactMarkdown>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  )
}
