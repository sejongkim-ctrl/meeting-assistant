import { useEffect, useRef, useState } from 'react'
import type { Note, ChatMsg } from '../types'
import { chatWithNote } from '../api/client'

interface Props {
  note: Note | null
}

export default function ChatPanel({ note }: Props) {
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Reset messages when note changes
  useEffect(() => {
    setMessages([])
  }, [note?.id])

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || !note || loading) return
    setInput('')

    const userMsg: ChatMsg = { role: 'user', content: text }
    const nextMessages = [...messages, userMsg]
    setMessages(nextMessages)
    setLoading(true)

    try {
      const res = await chatWithNote(note.id, nextMessages)
      setMessages(prev => [...prev, { role: 'assistant', content: res.content }])
    } catch (e) {
      const msg = e instanceof Error ? e.message : '오류가 발생했습니다.'
      setMessages(prev => [...prev, { role: 'assistant', content: `⚠️ ${msg}` }])
    } finally {
      setLoading(false)
    }
  }

  const hasContent = !!(note?.transcript?.length || note?.diarized_script?.length || note?.summary)

  return (
    <aside className="chat-panel">
      <div className="chat-header">AI 어시스턴트</div>
      <div className="chat-messages">
        {messages.length === 0 && (
          <p className="empty-hint">
            {!note
              ? '노트를 선택하면 AI와 대화할 수 있습니다.'
              : !hasContent
              ? '녹음 후 회의 내용에 대해 질문하세요.'
              : '회의 내용에 대해 무엇이든 물어보세요.\n예: "액션 아이템 정리해줘", "다음 회의 어젠다 뭐야?"'}
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            <p style={{ whiteSpace: 'pre-wrap' }}>{m.content}</p>
          </div>
        ))}
        {loading && (
          <div className="chat-msg assistant">
            <p className="chat-thinking">생각 중<span className="dot-anim">...</span></p>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="chat-input-row">
        <input
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()}
          placeholder={note ? '메시지 입력... (Enter로 전송)' : '노트를 선택하세요'}
          disabled={!note || loading}
        />
        <button className="send-btn" onClick={sendMessage} disabled={!note || loading || !input.trim()}>
          ↑
        </button>
      </div>
    </aside>
  )
}
