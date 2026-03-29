#!/bin/bash
# ─────────────────────────────────────────────
# start_tunnel.sh
# cloudflared 터널 시작 + Vercel/GitHub Pages 리다이렉트 자동 갱신
#
# 사용법:  bash start_tunnel.sh
# 효과:
#   1. 기존 cloudflared 프로세스 종료
#   2. 새 Quick Tunnel 시작
#   3. 발급된 URL을 meeting-assistant-link/index.html에 반영
#   4. Vercel 재배포 + GitHub Pages push → 고정 링크 갱신
# ─────────────────────────────────────────────

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LINK_REPO_DIR="$HOME/meeting-assistant-link"
TUNNEL_LOG="/tmp/cloudflared-tunnel.log"
VERCEL_URL="https://meeting-assistant-link.vercel.app"
GHPAGES_URL="https://sejongkim-ctrl.github.io/meeting/"

# ── 1. 기존 cloudflared 종료 ──
if pgrep -f "cloudflared tunnel" > /dev/null 2>&1; then
  echo "🔄 기존 터널 종료 중..."
  pkill -f "cloudflared tunnel" 2>/dev/null || true
  sleep 2
fi

# ── 2. 로그 초기화 + cloudflared Quick Tunnel 시작 (백그라운드) ──
> "$TUNNEL_LOG"
echo "🚀 새 터널 시작 중..."
cloudflared tunnel --url http://localhost:8502 >> "$TUNNEL_LOG" 2>&1 &
TUNNEL_PID=$!

# ── 3. URL 추출 대기 (최대 20초) ──
echo "⏳ 터널 URL 대기 중..."
TUNNEL_URL=""
for i in $(seq 1 40); do
  TUNNEL_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1 || true)
  if [ -n "$TUNNEL_URL" ]; then
    break
  fi
  sleep 0.5
done

if [ -z "$TUNNEL_URL" ]; then
  echo "❌ 터널 URL을 가져오지 못했습니다. 로그 확인: $TUNNEL_LOG"
  exit 1
fi

echo "✅ 터널 URL: $TUNNEL_URL"

# ── 4. index.html 에 URL 반영 ──
if [ ! -f "$LINK_REPO_DIR/index.html" ]; then
  echo "❌ $LINK_REPO_DIR/index.html 파일을 찾을 수 없습니다."
  exit 1
fi

sed -i '' "s|var TUNNEL_URL = \".*\"|var TUNNEL_URL = \"$TUNNEL_URL\"|" "$LINK_REPO_DIR/index.html"
echo "📝 index.html 업데이트 완료"

# ── 5. Vercel 재배포 (즉시 반영) ──
if command -v vercel > /dev/null 2>&1; then
  echo "🔺 Vercel 배포 중..."
  cd "$LINK_REPO_DIR"
  vercel --prod --yes > /dev/null 2>&1 &
  VERCEL_PID=$!
  echo "   Vercel 배포 시작 (PID: $VERCEL_PID)"
else
  echo "⚠️  Vercel CLI 없음 — Vercel 배포 생략"
fi

# ── 6. GitHub Pages push (백업) ──
cd "$LINK_REPO_DIR"
if [ -d ".git" ]; then
  if ! git diff --quiet index.html 2>/dev/null; then
    git add index.html
    git commit -m "update tunnel URL → ${TUNNEL_URL##*/}" --no-gpg-sign 2>/dev/null || true
    git push origin main 2>/dev/null &
    echo "📦 GitHub Pages push 시작"
  fi
fi

# ── 7. 결과 출력 ──
echo ""
echo "═══════════════════════════════════════════"
echo "  🎙️  AI 회의 어시스턴트 터널 준비 완료"
echo "═══════════════════════════════════════════"
echo ""
echo "  고정 링크 (팀 공유용):"
echo "  $VERCEL_URL"
echo ""
echo "  백업 링크:"
echo "  $GHPAGES_URL"
echo ""
echo "  직접 접속 (이번 세션):"
echo "  $TUNNEL_URL"
echo ""
echo "  cloudflared PID: $TUNNEL_PID"
echo "  로그: $TUNNEL_LOG"
echo "═══════════════════════════════════════════"
