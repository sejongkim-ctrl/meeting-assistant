import { useState } from 'react'
import type { Note } from '../types'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface Props {
  note: Note | null
}

export default function ChatPanel({ note }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || !note) return
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setLoading(true)

    try {
      const context = note.diarized_script ?? note.transcript ?? ''
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          note_id: note.id,
          template: 'free',
          custom_prompt: `회의 스크립트:\n${context}\n\n질문: ${text}`,
        }),
      })
      const data = await res.json()
      setMessages((prev) => [...prev, { role: 'assistant', content: data.result ?? '오류가 발생했습니다.' }])
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', content: '요청 중 오류가 발생했습니다.' }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <aside className="chat-panel">
      <div className="chat-header">AI 어시스턴트</div>
      <div className="chat-messages">
        {messages.length === 0 && (
          <p className="empty-hint">
            {note ? '회의 내용에 대해 질문하세요.' : '노트를 선택하면 AI와 대화할 수 있습니다.'}
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            <p>{m.content}</p>
          </div>
        ))}
        {loading && <div className="chat-msg assistant"><p>생각 중...</p></div>}
      </div>
      <div className="chat-input-row">
        <input
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()}
          placeholder={note ? '메시지 입력...' : '노트를 선택하세요'}
          disabled={!note || loading}
        />
        <button className="send-btn" onClick={sendMessage} disabled={!note || loading}>
          ↑
        </button>
      </div>
    </aside>
  )
}
