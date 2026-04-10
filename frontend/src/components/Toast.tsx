import type { Toast } from '../hooks/useToast'

interface Props {
  toasts: Toast[]
  onHide: (id: number) => void
}

export default function ToastContainer({ toasts, onHide }: Props) {
  if (toasts.length === 0) return null
  return (
    <div className="toast-container">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.type}`} onClick={() => onHide(t.id)}>
          {t.type === 'success' && <span className="toast-icon">✓</span>}
          {t.type === 'error' && <span className="toast-icon">✕</span>}
          {t.type === 'info' && <span className="toast-icon">ℹ</span>}
          <span className="toast-message">{t.message}</span>
        </div>
      ))}
    </div>
  )
}
