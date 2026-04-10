import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <div className="error-boundary-content">
            <div className="error-icon">⚠️</div>
            <h2>문제가 발생했습니다</h2>
            <p>{this.state.error?.message ?? '알 수 없는 오류'}</p>
            <button
              className="action-btn"
              onClick={() => this.setState({ hasError: false, error: null })}
            >
              다시 시도
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
